import streamlit as st
import pandas as pd
import backend as be

st.set_page_config(page_title="Airline Reservation System", layout="wide")

# ---------------- Session Initialization ----------------
defaults = {
    'selected_route': None,
    'selected_route_flight_ids': None,
    'passengers': [],
    'origin_suggestions': [],
    'destination_suggestions': [],
    'search_results': None,
    'user_bookings': None,
    'travel_purpose': None,
    'booking_completed': False
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


@st.cache_resource
def load_data():
    routes = be.fetch_all_routes_from_db()
    airports = be.fetch_all_airports_from_db()
    return be.build_graph(routes), be.build_airport_trie(airports)


graph, trie = load_data()

# ---------------- UI Menu ----------------
st.title("✈️ Next-Gen Airline Reservation System")
menu = ["Search Flights", "My Bookings", "Eco Leaderboard"]
choice = st.sidebar.radio("Navigate", menu)

# ---------------- Search Flights ----------------
if choice == "Search Flights":
    st.header("Search Flights with Purpose-based")

    c1, c2 = st.columns(2)
    with c1:
        src_prefix = st.text_input("From:")
        if src_prefix:
            st.session_state.origin_suggestions = trie.get_suggestions(src_prefix.upper())
        origin = st.radio("Select Origin", st.session_state.origin_suggestions, horizontal=True) if st.session_state.origin_suggestions else None
    with c2:
        dst_prefix = st.text_input("To:")
        if dst_prefix:
            st.session_state.destination_suggestions = trie.get_suggestions(dst_prefix.upper())
        dest = st.radio("Select Destination", st.session_state.destination_suggestions, horizontal=True) if st.session_state.destination_suggestions else None

    purpose = st.selectbox("Travel Purpose", ["Business", "Tourism", "Family Visit", "Education"], index=0)

    if st.button("Search Flights", use_container_width=True):
        if not origin or not dest:
            st.warning("Please select both origin and destination.")
        elif origin == dest:
            st.warning("Origin and destination cannot be same.")
        else:
            st.session_state.search_results = {}

            # ---- Fetch direct flight if available ----
            df_direct = be.get_direct_flights_from_db(origin, dest)
            if not df_direct.empty:
                r = df_direct.iloc[0].to_dict()
                r['price'] = float(r.get('price') or 0.0)
                r['available_seats'] = int(r.get('available_seats') or 0)
                r['distance_km'] = float(r.get('distance_km') or 0.0)
                st.session_state.search_results['direct'] = r

            # ---- Always compute purpose-based route even if direct exists ----
            route = None
            algo_used = ""

            if purpose in ["Business", "Family Visit"]:
                route = be.bfs_shortest_path(graph, origin, dest)
                algo_used = "BFS (Shortest Path)"
            elif purpose in ["Tourism", "Education"]:
                route, _ = be.find_cheapest_route(graph, origin, dest)
                algo_used = "Cheapest Route"
                if not route:
                    route = be.dfs_find_a_path(graph, origin, dest)
                    algo_used = "DFS (Fallback)"
            else:
                route = be.bfs_shortest_path(graph, origin, dest)
                algo_used = "BFS (Default)"

            # ---- Add connecting result display even if direct exists ----
            if route and len(route) > 2:
                flights, total, ok = be.get_flight_details_for_route(route)
                if ok:
                    st.session_state.search_results['connecting'] = {
                        'route': route,
                        'flights': flights,
                        'total_price': total,
                        'algorithm': algo_used
                    }

            # ---- Store travel purpose ----
            if st.session_state.search_results:
                st.session_state.travel_purpose = purpose
            else:
                alt, price = be.find_cheapest_route(graph, origin, dest)
                if alt:
                    st.info(f"No direct flight. Suggested alternate: {' → '.join(alt)} | ₹{price:.2f}")
                    if st.button("Book Suggested Route"):
                        f, t, ok = be.get_flight_details_for_route(alt)
                        if ok:
                            st.session_state.selected_route = alt
                            st.session_state.selected_route_flight_ids = [int(ff['flight_id']) for ff in f]
                            st.session_state.travel_purpose = purpose
                            st.rerun()
                        else:
                            st.error("Suggested route has no available seats now.")

    # ---------------- Display Search Results ----------------
    if st.session_state.search_results:
        st.subheader("Available Options")

        if 'direct' in st.session_state.search_results:
            d = st.session_state.search_results['direct']
            st.markdown(f"**Direct Flight:** {d.get('flight_number','-')}  |  ₹{d['price']:.2f}  |  Seats: {d['available_seats']}")
            co2 = be.estimate_carbon_emission(d.get('distance_km', 0))
            st.caption(f"Carbon footprint: {co2} kg CO₂ per passenger.")
            if st.button("Book Direct Flight", key="book_direct"):
                st.session_state.selected_route_flight_ids = [int(d['flight_id'])]
                st.session_state.selected_route = [d['origin'], d['destination']]
                st.rerun()

        if 'connecting' in st.session_state.search_results:
            c = st.session_state.search_results['connecting']
            st.markdown(f"**Connecting Route ({c['algorithm']}):** {' → '.join(c['route'])} | Total ₹{c['total_price']:.2f}")
            for fl in c['flights']:
                st.text(f" - {fl['flight_number']}: {fl['origin']} → {fl['destination']} | Seats: {fl['available_seats']} | ₹{fl['price']}")
            if st.button("Book Connecting Route", key="book_connect"):
                st.session_state.selected_route = c['route']
                st.session_state.selected_route_flight_ids = [int(f['flight_id']) for f in c['flights']]
                st.rerun()

# ---------------- Booking Flow ----------------
if st.session_state.selected_route:
    st.header("Book Your Flight")
    route = st.session_state.selected_route
    flight_ids = st.session_state.selected_route_flight_ids

    _, total_price_per_passenger, _ = be.get_flight_details_for_route(route)

    st.subheader("Your Information (Main Contact)")
    user_fname = st.text_input("First Name", key="user_fname")
    user_lname = st.text_input("Last Name", key="user_lname")
    user_email = st.text_input("Email", key="user_email")

    # Seat recommendation system
    seat_type = "Window"
    if user_email and user_email.strip() != "":
        try:
            recommended = be.get_user_seat_pref(user_email)
        except Exception:
            recommended = "Window"
        st.info(f"💺 Recommended seat type for you: **{recommended}**")
        try:
            seat_type = st.radio("Select preferred seat type:", ["Window", "Aisle", "Middle"],
                                 index=["Window", "Aisle", "Middle"].index(recommended),
                                 key="seat_type_select")
        except Exception:
            seat_type = st.radio("Select preferred seat type:", ["Window", "Aisle", "Middle"], key="seat_type_select")

    st.subheader("Passenger Details")
    with st.form("passenger_form", clear_on_submit=True):
        pcol1, pcol2, pcol3 = st.columns(3)
        p_fname = pcol1.text_input("Passenger First Name")
        p_lname = pcol2.text_input("Passenger Last Name")
        p_age = pcol3.number_input("Age", min_value=1, max_value=120, value=30)
        if st.form_submit_button("Add Passenger"):
            st.session_state.passengers.append({'first_name': p_fname, 'last_name': p_lname, 'age': p_age})
    if st.session_state.passengers:
        st.write(f"**Total Passengers:** {len(st.session_state.passengers)}")
        st.write(f"**Price per passenger:** ₹{total_price_per_passenger:.2f}")
        st.write(f"**Final Price:** ₹{total_price_per_passenger * len(st.session_state.passengers):.2f}")

    if st.button("Confirm Booking", use_container_width=True, type="primary"):
        if not (user_fname and user_lname and user_email):
            st.error("Please enter the main contact's details.")
        elif not st.session_state.passengers:
            st.error("Please add at least one passenger.")
        else:
            final_total = total_price_per_passenger * len(st.session_state.passengers)
            user_details = {
                'first_name': user_fname,
                'last_name': user_lname,
                'email': user_email,
                'travel_purpose': st.session_state.get('travel_purpose')
            }
            booking_id, msg = be.save_booking(user_details, st.session_state.passengers, flight_ids, final_total)
            if booking_id:
                st.session_state.booking_completed = True
                st.session_state.last_booking_id = booking_id
                st.session_state.last_booking_email = user_email
                st.success(f"{msg} Your Booking ID is: {booking_id}")
                try:
                    be.update_user_seat_pref(user_email, seat_type)
                except Exception:
                    pass

                flights_for_route, _, _ = be.get_flight_details_for_route(route)
                total_dist = sum([float(f.get('distance_km') or 0) for f in flights_for_route])
                total_pax = len(st.session_state.passengers)
                co2_total = be.estimate_carbon_emission(total_dist, total_pax)
                st.info(f"🌱 Estimated total CO₂ for this booking: {co2_total} kg")

                
                st.balloons()
                st.info("🎉 Booking completed successfully! You can offset your carbon footprint below.")
            else:
                st.error(f"Booking failed: {msg}")
# --- Carbon offset persists after booking ---
if st.session_state.get('booking_completed', False):
    st.markdown("### ♻️ Offset Your Carbon Footprint")
    st.write("You can voluntarily donate to offset your flight emissions.")

    booking_id = st.session_state.get('last_booking_id')
    user_email = st.session_state.get('last_booking_email')

    offset_choice = st.checkbox("Yes — I want to offset my carbon footprint (suggested ₹20)", key=f"offset_{booking_id}")

    if offset_choice:
        donation_amount = st.number_input(
            "Enter donation amount (₹)",
            min_value=1.0,
            value=20.0,
            step=1.0,
            key=f"don_{booking_id}"
        )
        if st.button("Confirm Offset", key=f"confirm_offset_{booking_id}"):
            ok = be.insert_carbon_offset(booking_id, user_email, donation_amount)
            if ok:
                # --- Compute CO₂ impact for this flight ---
                flights_for_route, _, _ = be.get_flight_details_for_route(route)
                total_dist = sum([float(f.get('distance_km') or 0) for f in flights_for_route])
                total_pax = len(st.session_state.passengers)
                co2_total = be.estimate_carbon_emission(total_dist, total_pax)

                # --- Fetch updated lifetime contribution ---
                leaderboard_data = be.get_eco_leaderboard(limit=100)
                user_entry = next((d for d in leaderboard_data if d['user_email'] == user_email), None)
                lifetime_total = user_entry['total_donation'] if user_entry else donation_amount

                # --- Thank-you summary popup ---
                st.markdown("""
                    <div style="background-color:#e8f5e9;padding:20px;border-radius:15px;margin-top:10px;">
                        <h3 style="color:#2e7d32;">🌱 Thank You for Offsetting Your Emissions!</h3>
                        <p style="color:#2e7d32; font-size:16px; margin:4px 0;"><b>Donation Recorded:</b> ₹{:.2f}</p>
                        <p style="color:#2e7d32; font-size:16px; margin:4px 0;"><b>CO₂ Offset for this Flight:</b> {} kg</p>
                        <p style="color:#1b5e20; font-size:16px; margin:4px 0;"><b>Your Total Contributions So Far:</b> ₹{:.2f}</p>
                        <p style="font-size:15px;color:#388e3c;">Together, we’re making air travel more sustainable. ✈️🌍</p>
                    </div>
                """.format(donation_amount, co2_total, lifetime_total),
                unsafe_allow_html=True)

                st.balloons()
                st.session_state.booking_completed = False
            else:
                st.error("Failed to record offset. Please try again.")


# ---------------- My Bookings ----------------
if choice == "My Bookings":
    st.header("My Bookings")
    email = st.text_input("Enter your email to find your bookings:", key="lookup_email")
    if st.button("Find My Bookings", use_container_width=True):
        if not email or email.strip() == "":
            st.warning("Please enter a valid email.")
        else:
            bookings, status = be.get_user_bookings_from_db(email)
            st.session_state.user_bookings = bookings
            st.info(f"Data status: **{status}**")

    if st.session_state.user_bookings:
        st.write("### Your Bookings")
        for booking in st.session_state.user_bookings:
            info = booking['booking_info']
            with st.container():
                st.markdown(f"#### 🧾 Booking ID: {info.get('booking_id')}  |  Status: **{info.get('status')}**  |  Total: ₹{info.get('total_price')}")
                col1, col2 = st.columns([1, 1])
                with col1:
                    if info.get('status') == 'CONFIRMED':
                        if st.button("Cancel Booking", key=f"cancel_{info.get('booking_id')}"):
                            lookup_email = email if email else ""
                            ok = be.cancel_booking_in_db(info.get('booking_id'), lookup_email)
                            if ok:
                                st.success("Booking cancelled successfully.")
                                st.rerun()
                            else:
                                st.error("Failed to cancel booking.")
                with col2:
                    if st.button("Show Details", key=f"show_{info.get('booking_id')}"):
                        details = be.get_booking_full_details(info.get('booking_id'))
                        if details:
                            with st.expander(f"Details for Booking #{info.get('booking_id')}", expanded=True):
                                bi = details['booking_info']
                                st.write(f"**Name:** {bi.get('user_fname')} {bi.get('user_lname')}")
                                st.write(f"**Email:** {bi.get('email')}")
                                st.write(f"**Booking Date:** {bi.get('booking_date')}")
                                st.write(f"**Purpose:** {bi.get('travel_purpose')}")
                                st.write(f"**Status:** {bi.get('status')}")
                                st.write(f"**Total Price:** ₹{bi.get('total_price'):.2f}")

                                st.subheader("Passengers")
                                dfp = pd.DataFrame(details['passengers'])
                                st.dataframe(dfp)

                                st.subheader("Flights")
                                dff = pd.DataFrame(details['flights'])
                                if not dff.empty:
                                    st.dataframe(dff[['flight_number', 'origin', 'destination', 'departure_time', 'arrival_time', 'price', 'airline_name']])
                                else:
                                    st.write("No flight data available.")

                                total_dist = sum([float(f.get('distance_km') or 0) for f in details['flights']])
                                total_pax = len(details['passengers'])
                                co2 = be.estimate_carbon_emission(total_dist, total_pax)
                                st.info(f"🌱 Estimated total CO₂: **{co2} kg**")

                                st.subheader("Feedback")
                                rating = st.slider("Rate your overall experience", 1, 5, 3, key=f"rate_{info.get('booking_id')}")
# ---------------- Eco Leaderboard ----------------
if choice == "Eco Leaderboard":
    st.header("🌍 Eco Leaderboard — Top Carbon Offset Contributors")

    # Fetch leaderboard data
    data = be.get_eco_leaderboard(limit=50)

    if not data or len(data) == 0:
        st.info("No offsets recorded yet.")
    else:
        df = pd.DataFrame(data)
        df = df.rename(columns={
            'user_email': 'Email',
            'total_donation': 'Total Donated (₹)',
            'donations': 'Donations Count'
        })
        df.index = range(1, len(df) + 1)
        st.subheader("🏅 Leaderboard")
        st.table(df[['Email', 'Total Donated (₹)', 'Donations Count']])

        # Bar chart for visualization
        st.subheader("📊 Donation Summary")
        st.bar_chart(df.set_index('Email')['Total Donated (₹)'])
