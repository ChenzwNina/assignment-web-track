from flask import Flask, render_template, redirect, make_response
import uuid
from flask import request
import psycopg2
import json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, wait
import requests
from classifier import classify
import time
from pathlib import Path
from contextlib import closing
import logging
from threading import Lock, Thread
import math


app = Flask(__name__)

app.logger.setLevel(logging.INFO)


BLOCKED_FILE = Path(__file__).resolve().parent / "blocked_advertisers.json"
blocked_lock = Lock()

auction_lock = Lock()

AUCTION_FILE = (
    Path(__file__).resolve().parent / "auction_history.json"
)

def save_auction_history(auction_history):
    with auction_lock:
        if AUCTION_FILE.exists():
            with open(AUCTION_FILE, "r") as file:
                histories = json.load(file)
        else:
            histories = []

        histories.append(auction_history)

        temp_file = AUCTION_FILE.with_suffix(".tmp")

        with open(temp_file, "w") as file:
            json.dump(histories, file, indent=2)

        temp_file.replace(AUCTION_FILE)

def load_blocked_domains():
    if not BLOCKED_FILE.exists():
        return {"badv": []}

    with open(BLOCKED_FILE, "r") as file:
        return json.load(file)


def get_blocked_domains():
    with blocked_lock:
        data = load_blocked_domains()
        return data.get("badv", [])


def save_blocked_domains(domains):
    with blocked_lock:
        data = load_blocked_domains()

        existing = data.get("badv", [])
        data["badv"] = sorted(set(existing + domains))

        temp_file = BLOCKED_FILE.with_suffix(".tmp")

        with open(temp_file, "w") as file:
            json.dump(data, file, indent=2)

        temp_file.replace(BLOCKED_FILE)

def get_db_connection():
    return psycopg2.connect(database="mydb")

# Get all search queries based on client_id
def get_search_queries(client_uuid):
    # Connet app with database "mydb"
    conn = get_db_connection()
    # Open a cursor to perform database operations
    cur = conn.cursor()
    # Retrieve search results from searches table
    cur.execute('SELECT query, ts FROM searches WHERE client_id = %s ORDER BY ts DESC, search_id DESC', (client_uuid,))
    retreived_items = cur.fetchall()
    returned_searches = []

    # Return in required json format
    for retreived_item in retreived_items:
        returned_searches.append({"query": f"{retreived_item[0]}", "ts": f"{retreived_item[1]}"})

    cur.close()
    conn.close()
    return returned_searches

# Get first_seen
def get_first_seen(client_uuid):
    # Connet app with database "mydb"
    conn = get_db_connection()
    # Open a cursor to perform database operations
    cur = conn.cursor()
    # Retrieve first seen
    cur.execute("""SELECT to_char(first_seen AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') FROM clients WHERE client_id = %s""", (client_uuid,))
    row = cur.fetchone()

    if row is None:
        return None
    
    cur.close()
    conn.close()

    return row[0]

# Get last_seen
def get_last_seen(client_uuid):
    # Connet app with database "mydb"
    conn = get_db_connection()
    # Open a cursor to perform database operations
    cur = conn.cursor()
    # Retrieve last seen
    cur.execute("""SELECT to_char(last_seen AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') FROM clients WHERE client_id = %s""", (client_uuid,))
    row = cur.fetchone()
    if row is None:
        return None
    cur.close()
    conn.close()
    return row[0]

def update_last_seen(client_uuid, current_timestamp):
    # Connet app with database "mydb"
    conn = get_db_connection()
    # Open a cursor to perform database operations
    cur = conn.cursor()
    # Save last seen
    cur.execute('UPDATE clients SET last_seen = %s WHERE client_id = %s', (current_timestamp, client_uuid))
    conn.commit()
    cur.close()
    conn.close()

def save_request(client_uuid, current_timestamp):
    # Connet app with database "mydb"
    conn = get_db_connection()
    # Open a cursor to perform database operations
    cur = conn.cursor()
    # Get the latest request_id
    cur.execute('SELECT MAX(request_id) FROM requests')
    # print(cur.fetchall())
    row = cur.fetchone()
    # print("here it is", row[0])

    if row[0] is None:
        current_request_id = 0
    else:
        max_request_id =  int(row[0])
        current_request_id = max_request_id + 1

    # Referrer
    referrer = request.referrer

    # Current path
    path = request.path

    # IP
    ip = request.remote_addr

    # User Agent
    agent = request.headers.get('User-Agent')

    # Timestamp
    current_timestamp = datetime.now(timezone.utc)
    
    # Save every request into requests table
    cur.execute('INSERT INTO requests(request_id, client_id, ts, ip, referer, path) VALUES(%s, %s, %s, %s, %s, %s)', (current_request_id, client_uuid, current_timestamp, ip, referrer, path))
    cur.execute('INSERT INTO agents(client_id, agent, time_stamp) VALUES(%s, %s, %s)', (client_uuid, agent, current_timestamp))
    conn.commit()

    cur.close()
    conn.close()
    return current_request_id

def save_searches(client_uuid, current_timestamp, current_request_id, search_query):
    # Connet app with database "mydb"
    conn = get_db_connection()
    
    # Open a cursor to perform database operations
    cur = conn.cursor()

    # Get the biggest search id so far
    cur.execute('SELECT MAX(search_id) FROM searches')

    # Get request id
    # print("fetchone", cur.fetchone()[0])
    row = cur.fetchone()
    print("here it is", row[0])

    if row[0] is None:
        current_search_id = 0
    else:
        max_search_id =  int(row[0])
        current_search_id = max_search_id + 1
    # print("prior", current_search_id)
    # print("current", current_search_id)
    # Save into query 
    cur.execute('INSERT INTO searches(search_id, client_id, request_id, query, ts) VALUES (%s, %s, %s, %s, %s)', (current_search_id, client_uuid, current_request_id, search_query, current_timestamp))

    conn.commit()
    cur.close()
    conn.close()

def get_latest_ip(client_uuid):
    # Connet app with database "mydb"
    conn = get_db_connection()
    
    # Open a cursor to perform database operations
    cur = conn.cursor()

    # Get the lastest request by ts and request id
    cur.execute('SELECT ip FROM requests WHERE client_id = %s ORDER BY ts DESC, request_id DESC LIMIT 1',(client_uuid,))
    row = cur.fetchone()
    # Latest ip

    if row is None:
        return None

    cur.close()
    conn.close()
    return str(row[0])

def get_all_ips(client_uuid):
    # Connet app with database "mydb"
    conn = get_db_connection()
    
    # Open a cursor to perform database operations
    cur = conn.cursor()

    # Get all requests of the client
    cur.execute('SELECT * FROM requests WHERE client_id = %s',(client_uuid,))
    rows = cur.fetchall()
    ips = []

    for row in rows:
        if row[3] not in ips:
            ips.append(row[3])

    cur.close()
    conn.close()
    
    return ips


def get_all_agents(client_uuid):
    # Connet app with database "mydb"
    conn = get_db_connection()
    
    # Open a cursor to perform database operations
    cur = conn.cursor()

    cur.execute("""SELECT agent FROM agents WHERE client_id = %s ORDER BY time_stamp DESC""",(client_uuid,))

    rows = cur.fetchall()

    all_agent = [row[0] for row in rows]
    latest_agent = all_agent[0] if all_agent else None

    cur.close()
    conn.close()
    return all_agent, latest_agent

RTB_BASE = "https://webtracking.sysnet.ucsd.edu/pa1/rtb/"

# One shared HTTP session for all DSP traffic. It keeps TCP/TLS connections to
# the DSP host open between auctions, so the 250ms tmax is spent waiting for
# the DSP's answer instead of on a fresh handshake every time.
http = requests.Session()
http.mount("https://", requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=16))

# Reused worker pool for fanning out bid requests
dsp_executor = ThreadPoolExecutor(max_workers=8)

DSP_LIST_TTL = 300  # seconds between refreshes of the DSP list
_dsp_cache = {"urls": None, "fetched_at": 0.0}

def get_dsp():
    # Fetch the DSP list once and cache it, instead of one extra HTTP round
    # trip per auction
    now = time.monotonic()
    if _dsp_cache["urls"] is None or now - _dsp_cache["fetched_at"] > DSP_LIST_TTL:
        try:
            response = http.get(RTB_BASE, timeout=5)
            _dsp_cache["urls"] = response.json()["bid"]
            _dsp_cache["fetched_at"] = now
            print("DSP LIST:", _dsp_cache["urls"], flush=True)
        except (requests.RequestException, ValueError, KeyError):
            if _dsp_cache["urls"] is None:
                raise
    return _dsp_cache["urls"]

def warm_up_connections():
    # Open one keep-alive connection per DSP (they share a host) so even the
    # first auction after a quiet period doesn't pay for a TLS handshake
    try:
        n = len(get_dsp())
    except Exception as exc:
        print("WARM-UP: could not fetch DSP list:", exc, flush=True)
        return
    futures = [dsp_executor.submit(http.get, RTB_BASE, timeout=5) for _ in range(n)]
    wait(futures, timeout=5)

def keep_connections_warm(interval=60):
    while True:
        warm_up_connections()
        time.sleep(interval)

Thread(target=keep_connections_warm, daemon=True).start()

BID_REQUEST_TEMPLATE = Path(__file__).resolve().parent / "../starter_3_4/part4/bid_request.example.json"

def build_rtb(the_data):
    # Resolved relative to this file, not the process CWD
    with open(BID_REQUEST_TEMPLATE) as file:
        data = json.load(file)
    
    rtb_id = str(uuid.uuid4()) # Auction ID
    data["id"] = rtb_id
    data["device"]["ua"] = the_data["latest_user_agent"] or request.headers.get("User-Agent", "")
    data["device"]["ip"] = request.remote_addr
    data["user"]["id"] = the_data["client_id"] or ""
    data["user"]["data"][0] ["segment"] = the_data["user_segments"]

    # Read blocked advertisers for this user
    data["badv"] = get_blocked_domains()

    return data

def build_openrtb_json(client_uuid):
    # A browser without a (known) boogle_id still gets an auction, just with
    # no history and therefore no segments to claim
    first_seen = last_seen = None
    searches, ips, agents = [], [], []
    known_user = False

    # Retrieve data of the user
    with closing(get_db_connection()) as conn:
        with conn.cursor() as cur:
            
            # Get first-seen and last-seen timestamp
            if client_uuid:
                cur.execute("""SELECT to_char(first_seen AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'), to_char(last_seen AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') FROM clients WHERE client_id = %s""", (client_uuid,))
                row = cur.fetchone()
                known_user = row is not None

            if known_user:
                first_seen, last_seen = row
                
                # Get search history
                cur.execute("""SELECT query, ts FROM searches WHERE client_id = %s ORDER BY ts DESC, search_id DESC""", (client_uuid,))

                searches = [
                    {"query": str(q), "ts": str(ts)}
                    for q, ts in cur.fetchall()
                ]

                # Get IP history
                cur.execute("""SELECT ip FROM requests WHERE client_id = %s ORDER BY ts DESC, request_id DESC""", (client_uuid,))

                ips = list(dict.fromkeys(
                    str(ip)
                    for (ip,) in cur.fetchall()
                    if ip is not None
                ))

                # Get user agents
                cur.execute("""SELECT agent FROM agents WHERE client_id = %s ORDER BY time_stamp DESC""", (client_uuid,))

                # Distinct user agents, most recent first. The model was trained on
                # the number of *distinct* UAs, while the agents table has one row
                # per request.
                agents = list(dict.fromkeys(row[0] for row in cur.fetchall() if row[0]))


    the_data = {
        "client_id": client_uuid if known_user else None,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "latest_ip": ips[0] if ips else None,
        "ips": ips,
        "searches": searches,
        "user_agents": agents,
        "latest_user_agent": agents[0] if agents else None,
        # Same shape as the training data: a list of raw Accept-Language header strings
        "accept_languages": [request.headers["Accept-Language"]] if request.headers.get("Accept-Language") else []
    }

    # Nothing to infer from for an unknown user; otherwise never let a model
    # error take the whole auction down
    if not known_user:
        the_data["user_segments"] = []
    else:
        try:
            the_data["user_segments"] = classify(the_data)
        except Exception as exc:
            app.logger.exception("classify failed: %s", exc)
            the_data["user_segments"] = []

    # Build openrtb
    return build_rtb(the_data)


def send_request(url, request_content, deadline):
    # `deadline` is shared by every DSP in this auction: whatever hasn't
    # arrived by then is ignored, no matter which DSP it came from.
    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        return None

    try:
        response = http.post(
            url,
            json=request_content,
            timeout=remaining
        )

        # Arrived after tmax
        if time.perf_counter() > deadline:
            return None

        if response.status_code != 200:
            return None

        # Not valid JSON -> treated as no bid instead of crashing the auction
        return response.json()
    except (requests.RequestException, ValueError):
        return None

# Check bidding from DSP
def check_if_valid(bid, result, request_content):

    try: 
        # Check id
        imp_id = request_content["imp"][0]["id"]
        if bid["impid"] != imp_id:
            return False
        # Check currency (OpenRTB: a missing `cur` means USD)
        if result.get("cur", "USD") != "USD":
            return False
        # Check size
        w =  request_content["imp"][0]["banner"]["format"][0]["w"]
        h =  request_content["imp"][0]["banner"]["format"][0]["h"]
        if bid["w"] != w or bid["h"] != h:
            return False
        # check price
        price = request_content["imp"][0]["bidfloor"]
        if not isinstance(bid["price"], (int, float)):
            return False

        # malformat checking
        if isinstance(bid["price"], bool):
            return False
        if not math.isfinite(bid["price"]):
            return False
        if bid["price"] < price:
            return False

        # A bid we can't display or bill is not a bid
        if not isinstance(bid.get("adm"), str) or not bid["adm"].strip():
            return False
        if not isinstance(bid.get("burl"), str) or not bid["burl"]:
            return False

        return True

    # Missing / wrongly-typed fields: malformed bid, filter it
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        print("MALFORMED BID:", bid, flush=True)
        return False

# Winning bid and display ad
def decide_winner(bid_responses, bid_floor):
    
    sorted_bids = sorted(bid_responses, key=lambda bid: bid["price"], reverse=True)

    winning_bid = sorted_bids[0]
    highest_price = winning_bid["price"]

    if len(sorted_bids) >= 2:
        second_price = sorted_bids[1]["price"]
    else:
        second_price = bid_floor
    
    pay = round(min(highest_price, max(second_price, bid_floor) + 0.01), 4)

    burl = winning_bid["burl"]

    ad_html = winning_bid["adm"]

    print(
        "ALL VALID BIDS:",
        [bid["price"] for bid in sorted_bids],
        flush=True
    )

    print(
        "HIGHEST PRICE:", highest_price,
        "SECOND PRICE:", second_price,
        "BID FLOOR:", bid_floor,
        "FINAL PRICE:", pay,
        flush=True
    )

    return ad_html, winning_bid, pay, burl



@app.route('/', methods = ['GET'])
def index():
    response = make_response(render_template('new_boogle.html'))

     # Get current timestamp
    current_timestamp = datetime.now(timezone.utc)

    conn = get_db_connection()
    cur = conn.cursor()
    client_uuid = request.cookies.get("boogle_id")

    # Check if the user has cookies or not
    if not client_uuid:

        client_uuid = str(uuid.uuid4())
        # 1-month cookie
        response.set_cookie("boogle_id", value=client_uuid, max_age=2592000, samesite="Lax")

        # Save the client into clients table
        cur.execute('INSERT INTO clients(client_id, first_seen, last_seen) VALUES (%s, %s, %s)', (client_uuid, current_timestamp, current_timestamp))
    else:
        cur.execute('UPDATE clients SET last_seen = %s WHERE client_id = %s', (current_timestamp, client_uuid))

    # User Agent
    agent = request.headers.get('User-Agent')

    cur.execute('INSERT INTO agents(client_id, agent, time_stamp) VALUES(%s, %s, %s)', (client_uuid, agent, current_timestamp))
    conn.commit()
    cur.close()
    conn.close()

    return response

def bill_winner(billing_url):
    try:
        http.get(billing_url, timeout=5)
    except requests.RequestException as exc:
        print("BILLING FAILED:", billing_url, exc, flush=True)


@app.route('/ad', methods = ['GET'])
def ad():
    # The iframe must always get a 200 with HTML: an empty slot on failure,
    # never a Flask error page
    try:
        return auction()
    except Exception as exc:
        app.logger.exception("auction failed: %s", exc)
        return "", 200


def auction():
    # Run a single auction for the user

    # Get bid list
    bid_list = get_dsp()

    # Get client id from cookie
    client_uuid = request.cookies.get("boogle_id")
    # Compile request content based on user id
    request_content = build_openrtb_json(client_uuid)

    # Bid floor
    bid_floor = request_content["imp"][0]["bidfloor"]

    mt = request_content["tmax"]/1000

    bid_responses = []

    # One shared tmax deadline for every DSP, started the moment the bid
    # requests go out (everything before this point is not the DSPs' time)
    deadline = time.perf_counter() + mt
    bidding = [dsp_executor.submit(send_request, url, request_content, deadline) for url in bid_list]

    # Only wait until the shared deadline
    done, not_done = wait(bidding, timeout=max(0, deadline - time.perf_counter()))
    for late in not_done:
        late.cancel()

    print(
        "AUCTION:", request_content["id"],
        "DSP COUNT:", len(bid_list),
        "DONE:", len(done),
        "NOT DONE:", len(not_done),
        "ELAPSED MS:", round((time.perf_counter() - deadline + mt) * 1000),
        flush=True
    )

    for i, response in enumerate(bidding):
        print(
            "AUCTION:", request_content["id"],
            "DSP:", bid_list[i],
            "DONE:", response in done,
            flush=True
        )

    for response in done:
        result = response.result()

        # Save all bids
        if isinstance(result, dict):
            for seatbid in result.get("seatbid", []):
                for bid in seatbid.get("bid", []):
                    print(
                        "RECEIVED BID:",
                        bid,
                        "CURRENCY:",
                        result.get("cur"),
                        flush=True
                    )

                    if check_if_valid(bid, result, request_content):
                        print("ACCEPTED BID:", bid.get("price"), flush=True)
                        bid_responses.append(bid)
                    else:
                        print("FILTERED BID:", bid.get("price"), flush=True)

    # If no bid
    if not bid_responses:
            return "", 200
    
    # Decide winner
    ad_html, winning_bid, pay, burl = decide_winner(bid_responses, bid_floor)
    # print("here is the add html", ad_html)

    # Keep what /ad/feedback needs (not the creative markup itself)
    auction_history = {k: v for k, v in winning_bid.items() if k != "adm"}
    auction_history["auction_id"] = request_content["id"]
    auction_history["client_id"] = client_uuid
    auction_history["paid"] = pay

    save_auction_history(auction_history)

    # Bill off the response path so the ad renders right away
    billing_url = burl.replace("${AUCTION_PRICE}", str(pay))
    dsp_executor.submit(bill_winner, billing_url)

    return ad_html, 200

    
@app.route('/jsontest', methods = ['GET'])
def jsontest():
    res = make_response({ "data" : "I am in CSE190/CSE291!"})
    # print(res.content_type)
    return res

@app.route('/search', methods = ['GET'])
def search():
    # print(request.path)
    search_query = request.args.get('q', "")
    if not search_query.strip():
        print('whitespace')
        response = redirect('/')
    else:
        
        # Get UUID from cookies
        client_uuid = request.cookies.get("boogle_id")

        # Get current timestamp
        current_timestamp = datetime.now(timezone.utc)

        # Output result
        response = redirect('/', code=303)
        # print('has something')

        # Save to requests
        current_request_id = save_request(client_uuid, current_timestamp)

        # Save to searches
        save_searches(client_uuid, current_timestamp, current_request_id, search_query)

        # Update last seen
        update_last_seen(client_uuid, current_timestamp)

    return response

@app.route('/api/history', methods = ['GET'])
def history():
        # Get UUID from cookies
        client_uuid = request.cookies.get("boogle_id")

        # If the client is not a new client
        if client_uuid:
            returned_searches = get_search_queries(client_uuid)
            res = make_response({ "client_id": f"{client_uuid}", "searches": returned_searches})
            # print(res.content_type)
            return res
        
        # If the client is a new client
        else:
            return []
        
@app.route('/dump', methods = ['GET'])
def dump():
    # Connet app with database "mydb"

    conn = get_db_connection()

    # Open a cursor to perform database operations
    cur = conn.cursor()

    # Get the biggest search id so far
    cur.execute('SELECT client_id FROM clients')

    clients = cur.fetchall()

    output = []

    for client in clients:
        client_uuid = str(client[0])
        returned_searches = get_search_queries(client_uuid)
        first_seen = get_first_seen(client_uuid)
        last_seen = get_last_seen(client_uuid)
        lastest_ip = get_latest_ip(client_uuid)
        ips = get_all_ips(client_uuid)

        output.append({"client_id": f"{client_uuid}", "first_seen": first_seen, "last_seen": last_seen, "latest_ip": lastest_ip, "ips": ips, "searches": returned_searches})

    res = make_response({"clients": output})

    cur.close()
    conn.close()
    return res

@app.route('/ad/feedback', methods = ['POST'])
def get_complaint():
    data = request.get_json()

    client_uuid = request.cookies.get("boogle_id")
    auction_id = data["auction_id"]
    event = data["event"]

    if event != "complaint":
        return {"status": "ignored"}, 200

    path = Path(__file__).resolve().parent / "auction_history.json"

    if not path.exists():
        return {"error": "Auction not found"}, 404
    
    with auction_lock:
        with open(AUCTION_FILE, "r") as file:
            histories = json.load(file)

    for history in histories:
        # .get(): older entries in the file may not have these keys
        if history.get("auction_id") == auction_id:
            adomain = history.get("adomain") or []

            save_blocked_domains(adomain)
            return {"status": "ok"}, 200
    return {"error": "Auction not found"}, 404


    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port="8000")

