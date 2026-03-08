# main.py
from threading import Thread
from database import init_database
from barber_bot import startbarber
from user_bot import startuser

# Initialize database
init_database()

Thread(target=startbarber).start()
Thread(target=startuser).start()

print("✅ NavbatGo bots are running...")
