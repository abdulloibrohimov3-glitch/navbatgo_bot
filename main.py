from threading import Thread
from time import sleep
from database import init_database
import os

# Initialize database ONCE
init_database()
sleep(1)

from admin_bot import startadmin
from barber_bot import startbarber
from user_bot import startuser
from admin_server import app  # import Flask app

def run_admin_bot():
    startadmin()

def run_barber():
    startbarber()

def run_user():
    startuser()

def run_web():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    t1 = Thread(target=run_admin_bot, name='admin_bot')
    t2 = Thread(target=run_barber, name='barber_bot')
    t3 = Thread(target=run_user, name='user_bot')
    t4 = Thread(target=run_web, name='web_server')

    t1.daemon = True
    t2.daemon = True
    t3.daemon = True
    t4.daemon = True

    t1.start()
    sleep(2)
    t2.start()
    sleep(2)
    t3.start()
    t4.start()

    print("✅ NavbatGo bots are running...")
    t1.join()
