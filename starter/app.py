from flask import Flask
from flask import render_template
from flask import make_response

app = Flask(__name__)

@app.route('/', methods = ['GET'])
def index():
    return render_template('boogle.html')


@app.route('/jsontest', methods = ['GET'])
def jsontest():
    res = make_response({ "data" : "I am in CSE190/CSE291!"})
    print(res.content_type)
    return res

if __name__ == "__main__":
    app.run(host="0.0.0.0", port="8000")

