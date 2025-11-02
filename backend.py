import mysql.connector
from collections import deque
import pandas as pd
import datetime

DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME')
}

booking_cache = {}

# ----------------- DB CONNECTION -----------------
def get_db_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except mysql.connector.Error as err:
        return None

# ----------------- TRIE (AIRPORT SEARCH) -----------------
class TrieNode:
    def __init__(self):
        self.children = {}
        self.is_end_of_word = False
        self.word = None

class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word):
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end_of_word = True
        node.word = word

    def get_suggestions(self, prefix):
        node = self.root
        for char in prefix:
            if char not in node.children:
                return []
            node = node.children[char]
        suggestions = []
        self._collect_all_words(node, suggestions)
        return suggestions

    def _collect_all_words(self, node, suggestions):
        if node.is_end_of_word:
            suggestions.append(node.word)
        for child in node.children.values():
            self._collect_all_words(child, suggestions)

def build_airport_trie(airports):
    trie = Trie()
    for airport in airports:
        trie.insert(airport)
    return trie

# ----------------- GRAPH FUNCTIONS -----------------
def build_graph(routes):
    graph = {}
    for origin, destination in routes:
        if origin not in graph:
            graph[origin] = []
        graph[origin].append(destination)
    return graph

def bfs_shortest_path(graph, origin, destination):
    if origin not in graph or destination not in graph:
        return None
    queue = deque([[origin]])
    visited = {origin}
    while queue:
        path = queue.popleft()
        node = path[-1]
        if node == destination:
            return path
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(list(path) + [neighbor])
    return None

def dfs_find_a_path(graph, origin, destination):
    if origin not in graph or destination not in graph:
        return None
    stack = [(origin, [origin])]
    visited = set()
    while stack:
        current, path = stack.pop()
        if current == destination:
            return path
        visited.add(current)
        for neighbor in reversed(graph.get(current, [])):
            if neighbor not in visited:
                stack.append((neighbor, path + [neighbor]))
    return None

# ----------------- DB FETCH FUNCTIONS -----------------
def fetch_all_airports_from_db():
    conn = get_db_connection()
    if not conn:
        return []
    query = "SELECT DISTINCT origin FROM flights UNION SELECT DISTINCT destination FROM flights"
    df = pd.read_sql(query, conn)
    conn.close()
    return pd.concat([df[col] for col in df.columns]).unique().tolist()

def fetch_all_routes_from_db():
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT origin, destination FROM flights WHERE available_seats > 0")
    routes = cursor.fetchall()
    cursor.close()
    conn.close()
    return routes

def get_direct_flights_from_db(origin, destination):
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    query = "SELECT * FROM flights WHERE origin = %s AND destination = %s AND available_seats > 0"
    df = pd.read_sql(query, conn, params=(origin, destination))
    conn.close()
    return df

def get_flight_details_for_route(route):
    if not route or len(route) < 2:
        return [], 0, True
    conn = get_db_connection()
    if not conn:
        return [], 0, False
    query_parts, params = [], []
    for i in range(len(route) - 1):
        query_parts.append("(origin = %s AND destination = %s)")
        params.extend([route[i], route[i + 1]])
    query = f"SELECT * FROM flights WHERE {' OR '.join(query_parts)}"
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    if len(df) < len(route) - 1:
        return [], 0, False
    ordered, total, ok = [], 0, True
    for i in range(len(route) - 1):
        leg = df[(df['origin'] == route[i]) & (df['destination'] == route[i + 1])]
        if leg.empty or leg.iloc[0]['available_seats'] == 0:
            ok = False
            break
        ordered.append(leg.iloc[0])
        total += leg.iloc[0]['price']
    return ordered, total, ok

# ----------------- NEW INNOVATIVE FEATURES -----------------
def find_cheapest_route(graph, origin, destination, max_stops=3):
    best = {'route': None, 'price': float('inf')}
    def dfs(node, path):
        if len(path) - 1 > max_stops:
            return
        if node == destination:
            flights, total, ok = get_flight_details_for_route(path)
            if ok and total < best['price']:
                best['price'] = total
                best['route'] = list(path)
            return
        for nb in graph.get(node, []):
            if nb not in path:
                dfs(nb, path + [nb])
    if origin not in graph or destination not in graph:
        return None, 0
    dfs(origin, [origin])
    if best['route']:
        return best['route'], best['price']
    else:
        return None, 0


def estimate_carbon_emission(distance_km, passengers=1):
    # avg 0.115 kg CO2 per passenger per km
    return round(distance_km * 0.115 * passengers, 2)

def insert_carbon_offset(booking_id, user_email, amount):
    print("🔍 insert_carbon_offset called with:", booking_id, user_email, amount)
    conn = get_db_connection()
    if not conn:
        print("❌ Database connection failed in insert_carbon_offset()")
        return False

    cur = conn.cursor()
    try:
        query = """
            INSERT INTO carbon_offset (booking_id, user_email, donation_amount)
            VALUES (%s, %s, %s)
        """
        cur.execute(query, (int(booking_id), str(user_email), float(amount)))
        conn.commit()
        print(f"✅ Carbon offset recorded: booking_id={booking_id}, user={user_email}, amount={amount}")
        return True
    except mysql.connector.Error as err:
        print(f"❌ MySQL Insert Error: {err}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()





def get_eco_leaderboard(limit=20):
    conn = get_db_connection()
    if not conn:
        return []
    q = """SELECT user_email, SUM(donation_amount) AS total_donation, COUNT(*) AS donations
           FROM carbon_offset GROUP BY user_email ORDER BY total_donation DESC LIMIT %s"""
    df = pd.read_sql(q, conn, params=(limit,))
    conn.close()
    return df.to_dict(orient='records')

# ----------------- BOOKING MANAGEMENT -----------------
def save_booking(user_details, passenger_list, flight_ids, total_price):
    conn = get_db_connection()
    if not conn:
        return None, "DB failed"
    cursor = conn.cursor()
    num_pax = len(passenger_list)
    try:
        conn.start_transaction()
        for fid in flight_ids:
            cursor.execute("SELECT available_seats FROM flights WHERE flight_id=%s FOR UPDATE", (int(fid),))
            r = cursor.fetchone()
            if not r or r[0] < num_pax:
                conn.rollback()
                return None, "Not enough seats"
        for fid in flight_ids:
            cursor.execute("UPDATE flights SET available_seats=available_seats-%s WHERE flight_id=%s",
                           (num_pax, int(fid)))
        cursor.execute("""INSERT INTO users (first_name,last_name,email)
                          VALUES (%s,%s,%s)
                          ON DUPLICATE KEY UPDATE user_id=LAST_INSERT_ID(user_id),
                          first_name=VALUES(first_name)""",
                       (user_details['first_name'], user_details['last_name'], user_details['email']))
        user_id = cursor.lastrowid or cursor.fetchone()[0]
        cursor.execute("INSERT INTO bookings (user_id,total_price,status,travel_purpose) VALUES (%s,%s,'CONFIRMED',%s)",
                       (user_id, total_price, user_details.get('travel_purpose')))
        booking_id = cursor.lastrowid
        cursor.executemany("INSERT INTO passengers (booking_id,first_name,last_name,age) VALUES (%s,%s,%s,%s)",
                           [(booking_id, p['first_name'], p['last_name'], p['age']) for p in passenger_list])
        for fid in flight_ids:
            cursor.execute("INSERT INTO booking_flights (booking_id,flight_id,num_passengers) VALUES (%s,%s,%s)",
                           (booking_id, int(fid), num_pax))
        conn.commit()
        return booking_id, "Booking successful!"
    except mysql.connector.Error as err:
        conn.rollback()
        return None, f"DB Error: {err}"
    finally:
        cursor.close()
        conn.close()

def cancel_booking_in_db(booking_id, user_email):
    conn = get_db_connection()
    if not conn:
        return False
    cur = conn.cursor()
    try:
        conn.start_transaction()
        cur.execute("SELECT flight_id,num_passengers FROM booking_flights WHERE booking_id=%s", (booking_id,))
        for fid, n in cur.fetchall():
            cur.execute("UPDATE flights SET available_seats=available_seats+%s WHERE flight_id=%s", (n, fid))
        cur.execute("UPDATE bookings SET status='CANCELLED' WHERE booking_id=%s", (booking_id,))
        conn.commit()
        if user_email in booking_cache:
            del booking_cache[user_email]
        return True
    except:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

# ----------------- FETCH BOOKINGS -----------------
def get_user_bookings_from_db(email):
    if email in booking_cache:
        return booking_cache[email], "Cache"
    conn = get_db_connection()
    if not conn:
        return [], "Error"
    q = """SELECT b.booking_id,b.booking_date,b.total_price,b.status,p.first_name,p.last_name,p.age
           FROM bookings b JOIN users u ON b.user_id=u.user_id
           JOIN passengers p ON b.booking_id=p.booking_id
           WHERE u.email=%s ORDER BY b.booking_id"""
    df = pd.read_sql(q, conn, params=(email,))
    conn.close()
    if df.empty:
        return [], "None"
    book = {}
    for _, row in df.iterrows():
        bid = row['booking_id']
        if bid not in book:
            book[bid] = {'booking_info': {'booking_id': bid, 'booking_date': row['booking_date'],
                                          'total_price': row['total_price'], 'status': row['status']},
                         'passengers': []}
        book[bid]['passengers'].append({'first_name': row['first_name'], 'last_name': row['last_name'], 'age': row['age']})
    out = list(book.values())
    booking_cache[email] = out
    return out, "DB"

def get_booking_full_details(booking_id):
    conn = get_db_connection()
    if not conn:
        return {}
    data = {}
    try:
        q1 = """SELECT b.booking_id,b.booking_date,b.total_price,b.status,b.travel_purpose,
                       u.first_name AS user_fname,u.last_name AS user_lname,u.email
                FROM bookings b JOIN users u ON b.user_id=u.user_id WHERE b.booking_id=%s"""
        dfb = pd.read_sql(q1, conn, params=(booking_id,))
        if dfb.empty:
            return {}
        data['booking_info'] = dfb.iloc[0].to_dict()
        dfp = pd.read_sql("SELECT first_name,last_name,age FROM passengers WHERE booking_id=%s", conn, params=(booking_id,))
        data['passengers'] = dfp.to_dict(orient='records')
        dff = pd.read_sql("""SELECT f.flight_number,f.origin,f.destination,f.departure_time,f.arrival_time,
                                      f.price,f.distance_km,a.airline_name
                             FROM booking_flights bf JOIN flights f ON bf.flight_id=f.flight_id
                             LEFT JOIN airline a ON f.airline_id=a.airline_id WHERE bf.booking_id=%s""",
                          conn, params=(booking_id,))
        data['flights'] = dff.to_dict(orient='records')
        return data
    finally:
        conn.close()
def save_feedback(booking_id, rating, comments):
    conn = get_db_connection()
    if not conn:
        return False
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO feedback (booking_id, rating, comments) VALUES (%s,%s,%s)",
                    (booking_id, rating, comments))
        conn.commit()
        return True
    except:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

# ----------------- SEAT PREF -----------------
def get_user_seat_pref(email):
    conn = get_db_connection()
    if not conn:
        return "Window"
    cur = conn.cursor()
    cur.execute("SELECT seat_pref FROM users WHERE email=%s", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else "Window"

def update_user_seat_pref(email, pref):
    conn = get_db_connection()
    if not conn:
        return False
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET seat_pref=%s WHERE email=%s", (pref, email))
        conn.commit()
        return True
    except:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


