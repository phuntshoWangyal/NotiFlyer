import sqlite3
import datetime

WEEK_START_DAY = 3 #THURSDAY(MONDAY = 0)

def get_week_start():
    today = datetime.date.today()
    days_since = (today.weekday() - WEEK_START_DAY) %7
    return str(today-datetime.timedelta(days=days_since))

def setup_database():
    conn = sqlite3.connect("deals.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seen_deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flyer_item_id TEXT,
            name TEXT,
            merchant_name TEXT,
            current_price REAL,
            date_seen TEXT,
            week_start TEXT
        )
    """)
    conn.commit()
    conn.close()

setup_database()

def is_deal_seen(flyer_item_id):
    conn = sqlite3.connect("deals.db")
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM seen_deals WHERE flyer_item_id =? AND week_start=?", (flyer_item_id,get_week_start()))
    result = cursor.fetchone()

    conn.close()
    return result is not None

def save_deal(flyer_item_id, name, merchant_name, current_price):
    conn = sqlite3.connect("deals.db")
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO seen_deals (flyer_item_id,name,merchant_name,current_price,date_seen,week_start)
        VALUES(?,?,?,?,?,?)    
    """, (flyer_item_id,name,merchant_name,current_price,str(datetime.date.today()), get_week_start()))

    conn.commit()
    conn.close()

