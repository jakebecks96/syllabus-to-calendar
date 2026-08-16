from collections import defaultdict
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from ics import Calendar, Event, DisplayAlarm
import io
import json
import re
import time
from pydantic import BaseModel, Field
import pypdf
import streamlit as st

# ReportLab imports for printable wall posters
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


# --- 1. STRUCTURED OUTPUT SCHEMAS ---
class ExtractedEvent(BaseModel):
    title: str = Field(description="Name of assignment, exam, quiz, game, practice, or smart alert")
    event_type: str = Field(description="Must be one of: exam, quiz, assignment, class_meeting, game, practice, training, prep_alert")
    date: str = Field(description="Primary date in YYYY-MM-DD format. If a range, pick start date.")
    time: str = Field(default="00:00", description="Start time in HH:MM (24-hour format). Default to 00:00 if unspecified.")
    description: str = Field(default="", description="Special instructions, room numbers, opponent, or prep notes.")

class SyllabusData(BaseModel):
    course_name: str
    events: list[ExtractedEvent]


# --- 2. CUSTOM THEMES & PROFILES ---
THEMES = {
    "Abby 💕 (Marquette CRNA)": {
        "exam": "final exam 💕",
        "quiz": "pop quiz 🌸",
        "assignment": "clinical prep ✨",
        "class_meeting": "lecture / lab 📚",
        "game": "event ✨",
        "practice": "skills lab 💉",
        "training": "clinical shift 🩺",
        "prep_alert": "study reminder 🌸",
        "primary_hex": "#E8629A",
        "accent_hex": "#FFF0F5",
        "bg_gradient": "linear-gradient(135deg, #FFF0F5 0%, #FFE4E1 100%)",
        "tagline": "✨ Marquette CRNA Clinical & Class Sync ✨",
        "poster_title": "Abby's Marquette CRNA Semester Schedule"
    },
    "Naismith 😈 (ASU Freshman)": {
        "exam": "death of this class 😈",
        "quiz": "mini torture session 💀",
        "assignment": "sentence served ⛓️",
        "class_meeting": "jail time ⛓️",
        "game": "tailgate / game day 🏈",
        "practice": "conditioning 💀",
        "training": "gym session ⛓️",
        "prep_alert": "survival warning 🚨",
        "primary_hex": "#7B1FA2",
        "accent_hex": "#F3E5F5",
        "bg_gradient": "linear-gradient(135deg, #F3E5F5 0%, #EDE7F6 100%)",
        "tagline": "😈 ASU Freshman Survival Protocol 😈",
        "poster_title": "Naismith's ASU Survival Syllabus"
    },
    "Jake ⚓ (Disgruntled Sailor in OK)": {
        "exam": "mandatory fun evaluation ⚓",
        "quiz": "random spot inspection 🪖",
        "assignment": "duty log submission 🫡",
        "class_meeting": "watch standing / muster ☕",
        "game": "rec battle ⚓",
        "practice": "field day drills 🪖",
        "training": "pt session 🫡",
        "prep_alert": "plan of the day memo 🚨",
        "primary_hex": "#1A365D",
        "accent_hex": "#E2E8F0",
        "bg_gradient": "linear-gradient(135deg, #EDF2F7 0%, #E2E8F0 100%)",
        "tagline": "⚓ Operation: Survive Oklahoma & Finish The Degree ⚓",
        "poster_title": "Jake's Operational Plan & Watch Bill (Blame Oklahoma)"
    },
    "Dom 🔒 (Senior DB & Master Welder)": {
        "exam": "lockdown test / heavy weld 🔒💥",
        "quiz": "coverage check 🔒",
        "assignment": "film study & fab reps 🏈⚡",
        "class_meeting": "chalk talk / shop time 🏈",
        "game": "friday night lights / game day 🏈💥",
        "practice": "lockdown drills 🔒",
        "training": "weld shop & lift ⚡🔥",
        "prep_alert": "coach's prep memo 🚨",
        "primary_hex": "#0C2340",
        "accent_hex": "#FEF3C7",
        "bg_gradient": "linear-gradient(135deg, #FEF3C7 0%, #FDE68A 100%)",
        "tagline": "🔒 Charlotte Catholic DB Playbook, Football & Shop Schedule 🔒",
        "poster_title": "Dom's Senior Year Master Schedule"
    },
    "Standard 📅": {
        "exam": "Exam",
        "quiz": "Quiz",
        "assignment": "Assignment Due",
        "class_meeting": "Class Meeting",
        "game": "Game",
        "practice": "Practice",
        "training": "Training",
        "prep_alert": "Reminder",
        "primary_hex": "#2563EB",
        "accent_hex": "#EFF6FF",
        "bg_gradient": "linear-gradient(135deg, #F8FAFC 0%, #EFF6FF 100%)",
        "tagline": "📅 Unified Academic & Extracurricular Dashboard",
        "poster_title": "Semester Master Schedule"
    }
}

MONTH_NAMES = {
    "01": "January", "02": "February", "03": "March", "04": "April",
    "05": "May", "06": "June", "07": "July", "08": "August",
    "09": "September", "10": "October", "11": "November", "12": "December"
}

ALERT_OPTIONS = [
    "2 Hours Before",
    "24 Hours Before",
    "72 Hours Before",
    "1 Week Before",
    "None"
]

ALERT_OFFSETS = {
    "2 Hours Before": timedelta(hours=-2),
    "24 Hours Before": timedelta(hours=-24),
    "72 Hours Before": timedelta(hours=-72),
    "1 Week Before": timedelta(weeks=-1),
    "None": None,
}


# --- 3. DOM'S PROCEDURAL LIFE-OPS ENGINE ---
PACKERS_2026_SCHEDULE = [
    ("2026-09-13", "13:00", "Packers Game Day 🏈 (Go Pack Go!)"),
    ("2026-09-20", "13:00", "Packers Game Day 🏈"),
    ("2026-09-27", "16:25", "Packers Game Day 🏈"),
    ("2026-10-04", "13:00", "Packers Game Day 🏈"),
    ("2026-10-11", "13:00", "Packers Game Day 🏈"),
    ("2026-10-18", "16:05", "Packers Game Day 🏈"),
    ("2026-10-25", "20:20", "Packers Sunday Night Football 🏈"),
    ("2026-11-01", "13:00", "Packers Game Day 🏈"),
    ("2026-11-08", "13:00", "Packers Game Day 🏈"),
    ("2026-11-15", "13:00", "Packers Game Day 🏈"),
    ("2026-11-22", "13:00", "Packers Game Day 🏈"),
    ("2026-11-26", "12:30", "Packers Thanksgiving Game 🦃🏈"),
    ("2026-12-06", "13:00", "Packers Game Day 🏈"),
    ("2026-12-13", "16:25", "Packers Game Day 🏈"),
    ("2026-12-20", "13:00", "Packers Game Day 🏈"),
]

def generate_dom_injected_events(extracted_events):
    injected = []

    # 1. Packers Schedule
    for game_date, game_time, game_title in PACKERS_2026_SCHEDULE:
        injected.append({
            "Course": "Life Ops 🫡",
            "Title": game_title,
            "EventType": "game",
            "Date": game_date,
            "Time": game_time,
            "Description": "Green Bay football. Clear the afternoon schedule.",
            "Alert": "2 Hours Before"
        })

    # 2. Key Date Directives (Barber, Gear Maintenance)
    injected.extend([
        {
            "Course": "Life Ops 🫡",
            "Title": "Barber / Pre-Game Clean Fade 💈",
            "EventType": "prep_alert",
            "Date": "2026-09-24",
            "Time": "16:30",
            "Description": "Get a fresh cut before Friday night's game.",
            "Alert": "24 Hours Before"
        },
        {
            "Course": "Life Ops 🫡",
            "Title": "Deep Clean Gear Bag & Take a Shower 🧼",
            "EventType": "practice",
            "Date": "2026-10-09",
            "Time": "20:00",
            "Description": "Wash the practice gear, helmet pads, and welding hood liner.",
            "Alert": "2 Hours Before"
        },
    ])

    # 3. Semester Date Range (Late Aug - Mid Dec 2026)
    start_dt = datetime(2026, 8, 24)
    end_dt = datetime(2026, 12, 18)
    
    current_dt = start_dt
    week_counter = 0
    booked_dates = {e["Date"] for e in extracted_events}

    while current_dt <= end_dt:
        date_str = current_dt.strftime("%Y-%m-%d")
        day_of_week = current_dt.weekday()  # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
        day_of_month = current_dt.day

        # A. Monthly Target: Read a book (1st of each month)
        if day_of_month == 1:
            injected.append({
                "Course": "Life Ops 🫡",
                "Title": "Read a Book 📖 (Monthly Target)",
                "EventType": "assignment",
                "Date": date_str,
                "Time": "19:00",
                "Description": "Pick a book and read for 45 minutes minimum.",
                "Alert": "24 Hours Before"
            })

        # B. Weekly Directive: Weld something new (Every Saturday)
        if day_of_week == 5:
            injected.append({
                "Course": "Life Ops 🫡",
                "Title": "Weld Something New ⚡🔥 (Shop Hours)",
                "EventType": "training",
                "Date": date_str,
                "Time": "10:30",
                "Description": "Strike an arc and fabricate something from scratch in the shop.",
                "Alert": "24 Hours Before"
            })

        # C. Weekly Directive: Text the sisters (Every Tuesday)
        if day_of_week == 1:
            injected.append({
                "Course": "Life Ops 🫡",
                "Title": "Text the Sisters 📱",
                "EventType": "assignment",
                "Date": date_str,
                "Time": "17:30",
                "Description": "Check in on the sisters. Send a text.",
                "Alert": "2 Hours Before"
            })

        # D. Bi-Weekly Directive: Call Jacob (Alternating Sundays)
        if day_of_week == 6 and (week_counter % 2 == 0):
            injected.append({
                "Course": "Life Ops 🫡",
                "Title": "Call Jacob ⚓ (OK Debrief)",
                "EventType": "class_meeting",
                "Date": date_str,
                "Time": "17:00",
                "Description": "Debrief on game tape, welding projects, and let Jacob rant about Oklahoma.",
                "Alert": "2 Hours Before"
            })

        # E. Twice-a-Week Study Blocks (Mon & Wed evenings, offset by 2 hours if booked)
        if day_of_week in (0, 2):
            study_time = "20:00" if date_str in booked_dates else "18:00"
            injected.append({
                "Course": "Academics 📚",
                "Title": "Lockdown Study Session 🧠⚡",
                "EventType": "assignment",
                "Date": date_str,
                "Time": study_time,
                "Description": "Dedicated study block. No distractions, finish assignments early.",
                "Alert": "2 Hours Before"
            })

        if day_of_week == 6:
            week_counter += 1

        current_dt += timedelta(days=1)

    return injected


# --- 4. HELPER FUNCTIONS & DIALOG ---
def sanitize_for_pdf(text: str) -> str:
    clean = re.sub(r'[^\x00-\x7F]+', '', text)
    return clean.strip()

@st.dialog("📄 How to Find Your Actual Course Schedule")
def show_missing_dates_modal(filename):
    st.warning(f"**`{filename}`** appears to be a general policy or grading document without specific calendar dates.")
    st.markdown("""
    ### Why did this happen?
    Many instructors separate **Course Policies** (Honorlock rules, grading scale, contact info) from the actual **Course Schedule / Assignment Due Dates**.

    ---
    ### How to get the file with dates in Canvas / Blackboard:
    
    1. **Option A: Look for a Separate Schedule Document**
       * In your course page, click **Modules** or **Syllabus**.
       * Look for an attachment titled **"Course Schedule"**, **"Semester Timeline"**, or **"Spring 2026 Calendar"**.
       
    2. **Option B: Export the Canvas Course Summary Table**
       * Go to the **Syllabus** tab inside your Canvas course.
       * Scroll down to the bottom table titled **"Course Summary"** (this lists every single homework, quiz, and test alongside its due date).
       * Press `Ctrl + P` (or `Cmd + P` on Mac) $\\rightarrow$ **Save as PDF** $\\rightarrow$ upload that file here!
    """)
    if st.button("Got it! 👍", use_container_width=True):
        st.rerun()


# --- 5. PRINTABLE WALL POSTER GENERATOR ---
def generate_wall_art_pdf(events, user_profile):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
    )
    story = []

    profile_cfg = THEMES.get(user_profile, THEMES["Standard 📅"])
    primary_color = colors.HexColor(profile_cfg["primary_hex"])
    accent_color = colors.HexColor(profile_cfg["accent_hex"])

    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'PosterTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=primary_color,
        alignment=1,
        spaceAfter=15
    )

    header_cell_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=12,
        textColor=colors.white
    )

    body_cell_style = ParagraphStyle(
        'BodyStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#222222")
    )

    story.append(Paragraph(profile_cfg["poster_title"], title_style))
    story.append(Spacer(1, 10))

    table_data = [[
        Paragraph("Course", header_cell_style),
        Paragraph("Date", header_cell_style),
        Paragraph("Event", header_cell_style),
        Paragraph("Details / Instructions", header_cell_style)
    ]]

    for item in events:
        event_display = sanitize_for_pdf(item["CleanTitle"])
        desc_display = sanitize_for_pdf(item["Description"]) if item["Description"] else "None"

        table_data.append([
            Paragraph(sanitize_for_pdf(item["Course"]), body_cell_style),
            Paragraph(item["Date"], body_cell_style),
            Paragraph(event_display, body_cell_style),
            Paragraph(desc_display, body_cell_style)
        ])

    poster_table = Table(table_data, colWidths=[110, 75, 145, 210])
    poster_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#DDDDDD")),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, accent_color]),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))

    story.append(poster_table)
    doc.build(story)
    buffer.seek(0)
    return buffer


# --- 6. STREAMLIT UI SETUP ---
st.set_page_config(page_title="Syllabus Sync", page_icon="📅", layout="wide")

# Session State
if "extracted_events" not in st.session_state:
    st.session_state.extracted_events = None

if "empty_files" not in st.session_state:
    st.session_state.empty_files = []

# Sidebar Configuration
with st.sidebar:
    st.markdown("### ⚙️ Profile & Settings")
    user_profile = st.selectbox("Choose Profile", list(THEMES.keys()), index=0)
    current_theme = THEMES.get(user_profile, THEMES["Standard 📅"])
    
    st.divider()
    api_key = st.secrets.get("GEMINI_API_KEY")
    if api_key:
        st.success("🔑 API Key Active")
    else:
        st.error("⚠️ Key missing in `secrets.toml`")

    if st.session_state.extracted_events or st.session_state.empty_files:
        st.divider()
        if st.button("🔄 Reset & Upload New Syllabi", use_container_width=True):
            st.session_state.extracted_events = None
            st.session_state.empty_files = []
            st.rerun()

# Dynamic Theme Styling
primary_color = current_theme["primary_hex"]
accent_bg = current_theme["accent_hex"]
bg_gradient = current_theme["bg_gradient"]

st.markdown(f"""
    <style>
        .stButton>button {{
            background: {primary_color} !important;
            color: white !important;
            border-radius: 8px !important;
            border: none !important;
            font-weight: 600 !important;
            padding: 0.55rem 1.2rem !important;
            transition: all 0.2s ease-in-out !important;
        }}
        .stButton>button:hover {{
            opacity: 0.9 !important;
            transform: translateY(-1px) !important;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important;
        }}
        .hero-banner {{
            background: {bg_gradient};
            border: 1px solid rgba(0,0,0,0.08);
            border-left: 6px solid {primary_color};
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 25px;
        }}
        .hero-title {{
            color: {primary_color};
            font-size: 26px;
            font-weight: 800;
            margin-bottom: 4px;
        }}
        .hero-subtitle {{
            color: #4A5568;
            font-size: 15px;
            font-weight: 500;
        }}
        .event-card {{
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-left: 4px solid {primary_color};
            border-radius: 10px;
            padding: 14px 18px;
            margin-bottom: 12px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.03);
        }}
        .badge-pill {{
            background: {accent_bg};
            color: {primary_color};
            font-size: 11px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 6px;
            display: inline-block;
        }}
    </style>
""", unsafe_allow_html=True)

# Hero Header Banner
st.markdown(f"""
    <div class="hero-banner">
        <div class="hero-title">{current_theme['tagline']}</div>
        <div class="hero-subtitle">Upload your course syllabi and extracurricular schedules to extract deadlines, configure phone alarms, and export synchronized calendars.</div>
    </div>
""", unsafe_allow_html=True)

# File Uploader
uploaded_files = st.file_uploader(
    "Drop your syllabus and schedule PDFs here", 
    type=["pdf"], 
    accept_multiple_files=True
)

# Step 1: Processing Syllabi with Gemini
if uploaded_files and api_key and not st.session_state.extracted_events:
    if st.button("🚀 Process Syllabi & Extract Events", use_container_width=True):
        client = genai.Client(api_key=api_key)
        all_extracted_events = []
        empty_files_found = []

        for pdf_file in uploaded_files:
            with st.status(f"Reading `{pdf_file.name}`...", expanded=True) as status:
                
                prompt_text = """
                Parse all deadlines, exams, homework, quizzes, sports games, practices, and class sessions from this document.

                Rules:
                1. Assume academic year is 2026 unless specified otherwise.
                2. Convert all dates to YYYY-MM-DD format.
                3. Convert times to 24-hour HH:MM format (default to "00:00" for all-day).
                4. Categorize items into: 'exam', 'quiz', 'assignment', 'class_meeting', 'game', 'practice', 'training', 'prep_alert'.
                5. Put room numbers, opponent names, uniform instructions, or conditions into 'description'.
                6. In 'title', provide a short clean name (e.g. 'HW 1', 'Midterm 1', 'vs Catholic', 'Two-a-days') without repeating the course name.
                """

                # Hybrid PDF Inspection
                st.write("🔍 Inspecting document format...")
                reader = pypdf.PdfReader(pdf_file)
                pdf_text = "".join([page.extract_text() or "" for page in reader.pages])

                if len(pdf_text.strip()) > 100:
                    st.write("⚡ Plain text detected! Processing fast-lane...")
                    contents_payload = [f"{prompt_text}\n\nSyllabus Content:\n{pdf_text}"]
                else:
                    st.write("📷 Scanned PDF detected! Running OCR Vision analysis...")
                    pdf_bytes = pdf_file.getvalue()
                    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
                    contents_payload = [pdf_part, prompt_text]

                # Gemini API Call
                st.write("🤖 Extracting schedule with Gemini...")
                target_model = "gemini-3.5-flash"
                max_retries = 4
                response = None

                for attempt in range(max_retries):
                    try:
                        response = client.models.generate_content(
                            model=target_model,
                            contents=contents_payload,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                response_schema=SyllabusData,
                                temperature=0.1,
                            ),
                        )
                        break
                    except Exception as e:
                        error_msg = str(e)
                        if ("503" in error_msg or "UNAVAILABLE" in error_msg or "overloaded" in error_msg.lower()) and attempt < max_retries - 1:
                            wait_seconds = (attempt + 1) * 3
                            st.write(f"⏳ Server busy (503). Retrying in {wait_seconds}s...")
                            time.sleep(wait_seconds)
                        else:
                            status.update(label=f"❌ Error in {pdf_file.name}", state="error")
                            st.error(f"Details: {e}")
                            break

                # Parse JSON Output
                parsed_data = None
                if response:
                    if hasattr(response, 'parsed') and response.parsed:
                        parsed_data = response.parsed
                    elif response.text:
                        try:
                            clean_json = response.text.replace("```json", "").replace("```", "").strip()
                            parsed_data = SyllabusData.model_validate_json(clean_json)
                        except Exception:
                            pass

                if parsed_data and parsed_data.events:
                    st.write(f"✓ Found {len(parsed_data.events)} events for **{parsed_data.course_name}**.")

                    for item in parsed_data.events:
                        all_extracted_events.append({
                            "Course": parsed_data.course_name,
                            "Title": item.title,
                            "EventType": item.event_type.lower(),
                            "Date": item.date,
                            "Time": item.time if item.time != "00:00" else "All Day",
                            "Description": item.description
                        })

                    status.update(label=f"✅ Finished {pdf_file.name}!", state="complete", expanded=False)
                else:
                    empty_files_found.append(pdf_file.name)
                    status.update(label=f"⚠️ No date schedule found in {pdf_file.name}", state="complete", expanded=False)

        st.session_state.empty_files = empty_files_found

        # Inject Dom's Life-Ops Engine if Dom profile is active
        if "Dom" in user_profile:
            dom_injected = generate_dom_injected_events(all_extracted_events)
            all_extracted_events.extend(dom_injected)

        if all_extracted_events:
            all_extracted_events.sort(key=lambda x: (x["Date"], x["Time"]))
            st.session_state.extracted_events = all_extracted_events
            st.rerun()
        elif empty_files_found:
            st.rerun()

# Warning & Guidance Card for policy-only files
if st.session_state.empty_files and not st.session_state.extracted_events:
    for empty_file in st.session_state.empty_files:
        st.warning(f"⚠️ No calendar schedule or dates were found in **`{empty_file}`**.")
        if st.button(f"📖 How to find the Schedule for {empty_file}", key=f"btn_{empty_file}", use_container_width=True):
            show_missing_dates_modal(empty_file)

# Step 2: Custom Notification Options & Interactive View
if st.session_state.extracted_events:
    raw_events = st.session_state.extracted_events

    # Show warning if some files had no dates
    if st.session_state.empty_files:
        with st.expander(f"⚠️ Notice: {len(st.session_state.empty_files)} uploaded file(s) contained no dates"):
            for ef in st.session_state.empty_files:
                st.write(f"• `{ef}` had no calendar schedule.")
                if st.button(f"📖 Help with `{ef}`", key=f"help_{ef}"):
                    show_missing_dates_modal(ef)

    # Summary Metrics Row
    exam_count = sum(1 for e in raw_events if e["EventType"] == "exam")
    quiz_count = sum(1 for e in raw_events if e["EventType"] == "quiz")
    hw_count = sum(1 for e in raw_events if e["EventType"] == "assignment")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Events", len(raw_events))
    m2.metric("Major Exams", exam_count)
    m3.metric("Quizzes & Checks", quiz_count)
    m4.metric("Assignments / Tasks", hw_count)

    # Custom Notification Options Bar
    st.divider()
    st.subheader("🔔 Configure Calendar Alerts")
    st.caption("Select your phone notification lead times for each category before downloading your `.ics` file:")

    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        exam_alert = st.selectbox("Exams & Games", ALERT_OPTIONS, index=3)       # Default: 1 Week Before
    with col_b:
        hw_alert = st.selectbox("Homework & Tasks", ALERT_OPTIONS, index=1)       # Default: 24 Hours Before
    with col_c:
        quiz_alert = st.selectbox("Quizzes & Checks", ALERT_OPTIONS, index=1)     # Default: 24 Hours Before
    with col_d:
        class_alert = st.selectbox("Class & Practice", ALERT_OPTIONS, index=0)    # Default: 2 Hours Before

    # Build Calendar and Poster Deliverables
    master_calendar = Calendar()
    formatted_dashboard_events = []
    theme_cfg = THEMES.get(user_profile, THEMES["Standard 📅"])

    for item in raw_events:
        event_prefix = theme_cfg.get(item["EventType"], item["EventType"])
        full_calendar_title = f"[{item['Course']}] {event_prefix}: {item['Title']}"
        clean_poster_title = f"{event_prefix.capitalize()}: {item['Title']}"

        cal_event = Event()
        cal_event.name = full_calendar_title
        cal_event.description = item["Description"]

        try:
            if item["Time"] and item["Time"] != "All Day":
                cal_event.begin = f"{item['Date']} {item['Time']}:00"
            else:
                cal_event.begin = item["Date"]
                cal_event.make_all_day()
        except Exception:
            cal_event.begin = item["Date"]
            cal_event.make_all_day()

        # Match selected alert
        event_cat = item["EventType"]
        selected_alert_str = "None"
        if event_cat in ("exam", "game"):
            selected_alert_str = exam_alert
        elif event_cat in ("assignment", "training"):
            selected_alert_str = hw_alert
        elif event_cat == "quiz":
            selected_alert_str = quiz_alert
        elif event_cat in ("class_meeting", "practice", "prep_alert"):
            selected_alert_str = class_alert

        alert_offset = ALERT_OFFSETS.get(selected_alert_str)
        if alert_offset:
            alarm = DisplayAlarm(trigger=alert_offset)
            cal_event.alarms.append(alarm)

        master_calendar.events.add(cal_event)
        formatted_dashboard_events.append({
            "Course": item["Course"],
            "Title": full_calendar_title,
            "CleanTitle": clean_poster_title,
            "Date": item["Date"],
            "Time": item["Time"],
            "Description": item["Description"],
            "Alert": selected_alert_str,
            "Type": item["EventType"]
        })

    # Timeline Schedule View
    st.divider()
    st.subheader("📅 Interactive Semester Schedule")

    events_by_month = defaultdict(list)
    for ev in formatted_dashboard_events:
        month_key = ev["Date"][:7]
        events_by_month[month_key].append(ev)

    sorted_month_keys = sorted(events_by_month.keys())
    tab_labels = []
    for mk in sorted_month_keys:
        year, month_num = mk.split("-")
        month_name = MONTH_NAMES.get(month_num, month_num)
        tab_labels.append(f"📆 {month_name} {year}")

    tabs = st.tabs(tab_labels)

    for tab, month_key in zip(tabs, sorted_month_keys):
        with tab:
            month_events = events_by_month[month_key]
            
            for ev in month_events:
                date_obj = datetime.strptime(ev["Date"], "%Y-%m-%d")
                formatted_date = date_obj.strftime("%A, %b %d")
                alert_text = f" • 🔔 Alert: {ev['Alert']}" if ev['Alert'] != "None" else ""

                st.markdown(f"""
                    <div class="event-card">
                        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;">
                            <span style="font-weight: 700; font-size: 16px; color: #1A202C;">{ev['CleanTitle']}</span>
                            <span class="badge-pill">{ev['Course']}</span>
                        </div>
                        <div style="color: #718096; font-size: 13px; font-weight: 500;">
                            🗓️ {formatted_date} • ⏰ {ev['Time']}{alert_text}
                        </div>
                        {f'<div style="margin-top: 6px; font-size: 13px; color: #4A5568;">📌 {ev["Description"]}</div>' if ev["Description"] else ''}
                    </div>
                """, unsafe_allow_html=True)

    with st.expander("📋 View Master Data Table"):
        st.dataframe(formatted_dashboard_events, use_container_width=True)

    # Deliverables Download Section
    ics_data = master_calendar.serialize()
    pdf_data = generate_wall_art_pdf(formatted_dashboard_events, user_profile)

    st.divider()
    st.subheader("📥 Export Deliverables")
    col1, col2 = st.columns(2)
    
    safe_profile_name = user_profile.split()[0].lower()
    with col1:
        st.download_button(
            label="📱 Download Phone Calendar (.ics)",
            data=ics_data,
            file_name=f"calendar_{safe_profile_name}.ics",
            mime="text/calendar",
            use_container_width=True
        )
    with col2:
        st.download_button(
            label="🎨 Download Printable Wall Poster (.pdf)",
            data=pdf_data,
            file_name=f"wall_poster_{safe_profile_name}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

elif not api_key:
    st.warning("⚠️ Backend API Key missing. Please ensure `.streamlit/secrets.toml` is configured.")