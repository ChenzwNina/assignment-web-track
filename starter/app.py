from flask import Flask
from flask import render_template, redirect
from flask import make_response
import uuid
from flask import request
import psycopg2
from datetime import datetime, timezone

app = Flask(__name__)

def get_db_connection():
    return psycopg2.connect(database="mydb")

# Get all search queries based on client_id
def get_search_queries(client_uuid):
    # Connet app with database "mydb"
    conn = get_db_connection()
    # Open a cursor to perform database operations
    cur = conn.cursor()
    # Retrieve search results from searches table
    cur.execute('SELECT query, ts FROM searches WHERE client_id = %s', (client_uuid,))
    retreived_items = cur.fetchall()
    returned_searches = []

    # Return in required json format
    for retreived_item in retreived_items:
        returned_searches.append({"query": f"{retreived_item[0]}", "ts": f"{retreived_item[1]}"})
    
    return returned_searches

# Get first_seen
def get_first_seen(client_uuid):
    # Connet app with database "mydb"
    conn = get_db_connection()
    # Open a cursor to perform database operations
    cur = conn.cursor()
    # Retrieve first seen
    cur.execute('SELECT first_seen FROM clients WHERE client_id = %s', (client_uuid,))
    first_seen = cur.fetchall()[0]
    return str(first_seen)

# Get last_seen
def get_last_seen(client_uuid):
    # Connet app with database "mydb"
    conn = get_db_connection()
    # Open a cursor to perform database operations
    cur = conn.cursor()
    # Retrieve last seen
    cur.execute('SELECT last_seen FROM clients WHERE client_id = %s', (client_uuid,))
    last_seen = cur.fetchall()[0]
    return str(last_seen)

def update_last_seen(client_uuid, current_timestamp):
    # Connet app with database "mydb"
    conn = get_db_connection()
    # Open a cursor to perform database operations
    cur = conn.cursor()
    # Save last seen
    cur.execute('UPDATE clients SET last_seen = %s WHERE client_id = %s', (current_timestamp, client_uuid,))
    conn.commit()

def save_request(client_uuid, current_timestamp):
    # Connet app with database "mydb"
    conn = get_db_connection()
    # Open a cursor to perform database operations
    cur = conn.cursor()
    # Get the latest request_id
    cur.execute('SELECT MAX(request_id) FROM requests')
    # print(cur.fetchall())
    row = cur.fetchone()
    print("here it is", row[0])

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

    # Save every request into requests table
    cur.execute('INSERT INTO requests(request_id, client_id, ts, ip, referer, path) VALUES(%s, %s, %s, %s, %s, %s)', (current_request_id, client_uuid, current_timestamp, ip, referrer, path))
    conn.commit()
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
    print("current", current_search_id)
    # Save into query 
    cur.execute('INSERT INTO searches(search_id, client_id, request_id, query, ts) VALUES (%s, %s, %s, %s, %s)', (current_search_id, client_uuid, current_request_id, search_query, current_timestamp))

    conn.commit()

def get_latest_ip(client_uuid):
    # Connet app with database "mydb"
    conn = get_db_connection()
    
    # Open a cursor to perform database operations
    cur = conn.cursor()

    # Get the lastest request by ts and request id
    cur.execute('SELECT * FROM requests WHERE client_id = %s ORDER BY ts DESC, request_id DESC LIMIT 1',(client_uuid,))
    row = cur.fetchall()[0]
    # Latest ip
    latest_ip = row[3]

    return str(latest_ip)

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
    
    return ips



@app.route('/', methods = ['GET'])
def index():
    response = make_response(render_template('boogle.html'))

    # Check if the user has cookies or not
    if not request.cookies.get("boogle_id"):

        client_uuid = str(uuid.uuid4())
        # 1-month cookie
        response.set_cookie("boogle_id", value=client_uuid, max_age=2592000, samesite="Lax")

        # Get current timestamp
        current_timestamp = datetime.now(timezone.utc)

        conn = get_db_connection()
        cur = conn.cursor()

        # Save the client into clients table
        cur.execute('INSERT INTO clients(client_id, first_seen, last_seen) VALUES (%s, %s, %s)', (client_uuid, current_timestamp, current_timestamp))
        conn.commit()

    return response


@app.route('/jsontest', methods = ['GET'])
def jsontest():
    res = make_response({ "data" : "I am in CSE190/CSE291!"})
    # print(res.content_type)
    return res

@app.route('/search', methods = ['GET'])
def search():
    # print(request.path)
    search_query = request.args.get('q')
    if search_query.isspace() or search_query=="":
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
    client_uuid = request.cookies.get("boogle_id")

    if client_uuid:
        returned_searches = get_search_queries(client_uuid)
        first_seen = get_first_seen(client_uuid)
        last_seen = get_last_seen(client_uuid)
        lastest_ip = get_latest_ip(client_uuid)
        ips = get_all_ips(client_uuid)
        res = make_response({ "client_id": f"{client_uuid}", "first_seen": f"{first_seen}", "last_seen": f"{last_seen}", "latest_ip": lastest_ip, "ips": ips, "searches": returned_searches})
        return res
    else:
        return []
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port="8000")

