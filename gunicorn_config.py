from web_server import app

if __name__ == "__main__":
    app.run()

# Gunicorn config - disable buffering for streaming
bind = "0.0.0.0:$PORT"
workers = 1
timeout = 120
preload_app = False
sendfile = False
