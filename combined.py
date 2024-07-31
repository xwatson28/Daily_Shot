import streamlit as st
import requests
import os
import re
import threading
from flask import Flask
from bs4 import BeautifulSoup, Comment
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
from PIL import Image
import io
from urllib.parse import urljoin
import schedule
import time
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import base64
import html
from urllib.parse import urljoin
from datetime import datetime

# Flask server code
app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return "No file part", 400
    file = request.files['file']
    if file.filename == '':
        return "No selected file", 400
    if file and file.filename.endswith('.html'):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)
        return jsonify(message="File uploaded successfully", filename=file.filename), 200
    else:
        return "Invalid file type", 400

@app.route('/view/<filename>', methods=['GET'])
def view_file(filename):
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    except FileNotFoundError:
        return "File not found", 404

@app.route('/files', methods=['GET'])
def list_files():
    files = os.listdir(app.config['UPLOAD_FOLDER'])
    return jsonify(files), 200

@app.route('/clear', methods=['POST'])
def clear_uploads():
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                os.rmdir(file_path)
        except Exception as e:
            return f"Failed to delete {file_path}. Reason: {e}", 500
    return "All files cleared", 200

def run_flask():
    app.run(host='0.0.0.0', port=5000)

# Gmail export code
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
TARGET_EMAILS = ['xwatson28@gmail.com', 'xavierjohnwatson@gmail.com', 'zack@cliftonfirst.com']
UPLOAD_URL = 'http://127.0.0.1:5000/upload'
NOTIFY_URL = 'http://127.0.0.1:5000/notify'

def save_email_as_html(subject, sender, body):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"Test_{timestamp}.html"
    with open(filename, 'w', encoding='utf-8') as file:
        file.write(f"<h1>{html.escape(subject)}</h1>")
        file.write(f"<p><b>From:</b> {html.escape(sender)}</p>")
        file.write(body)
    print(f"Email saved as {filename}")
    return filename

def process_html_body(body, base_url):
    if body is None:
        return ""
    
    if not body.strip().lower().startswith('<html>'):
        body = f"<html><head></head><body>{body}</body></html>"
    
    soup = BeautifulSoup(body, 'html.parser')
    
    for img in soup.find_all('img'):
        if 'src' in img.attrs:
            img['src'] = urljoin(base_url, img['src'])
    
    for link in soup.find_all('a'):
        if 'href' in link.attrs:
            link['href'] = urljoin(base_url, link['href'])
    
    body = str(soup)
    body = remove_forwarded_message_section(body)
    return body

def remove_forwarded_message_section(body):
    print("Original body length:", len(body))
    pattern = re.compile(r'(---------- Forwarded message ----------.*?Read the Daily Shot online)', re.DOTALL)
    match = pattern.search(body)
    if match:
        print("Forwarded message section found.")
        print("Matched section:", match.group(0))
        body = body.replace(match.group(0), 'Read the Daily Shot online')
    else:
        print("No forwarded message section found.")
    print("Modified body length:", len(body))
    return body

def upload_file(filename):
    with open(filename, 'rb') as file:
        files = {'file': (filename, file, 'text/html')}
        response = requests.post(UPLOAD_URL, files=files)
        if response.status_code == 200:
            print(f"File {filename} uploaded successfully.")
        else:
            print(f"Failed to upload file {filename}. Status code: {response.status_code}")

def notify_update():
    response = requests.get(NOTIFY_URL)
    if response.status_code == 200:
        print("Website notified successfully.")
    else:
        print(f"Failed to notify website. Status code: {response.status_code}")

def fetch_emails(service, email):
    query = f"from:{email}"
    results = service.users().messages().list(userId='me', q=query, maxResults=1).execute()
    messages = results.get('messages', [])
    return messages

def process_latest_email():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)
    all_messages = []
    for email in TARGET_EMAILS:
        messages = fetch_emails(service, email)
        all_messages.extend(messages)
    
    if not all_messages:
        print('No messages found from the specified email addresses.')
        return
    
    latest_message = all_messages[0]
    msg = service.users().messages().get(userId='me', id=latest_message['id']).execute()
    payload = msg.get('payload')
    headers = payload.get('headers')
    subject = sender = ""
    for header in headers:
        if header.get('name') == 'Subject':
            subject = header.get('value')
        if header.get('name') == 'From':
            sender = header.get('value')

    body = ""
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                body_data = part['body']['data']
                body_data = body_data.replace("-", "+").replace("_", "/")
                decoded_data = base64.b64decode(body_data)
                body += decoded_data.decode('utf-8')
            elif part['mimeType'] == 'text/html':
                body_data = part['body']['data']
                body_data = body_data.replace("-", "+").replace("_", "/")
                decoded_data = base64.b64decode(body_data)
                body += decoded_data.decode('utf-8')
        if body:
            body = process_html_body(body, "https://thedailyshot.com")
    else:
        body_data = payload['body'].get('data')
        if body_data:
            body_data = body_data.replace("-", "+").replace("_", "/")
            decoded_data = base64.b64decode(body_data)
            body = decoded_data.decode('utf-8')
            body = process_html_body(body, "https://thedailyshot.com")

    if body:
        print(f"Uploading email with subject: {subject}")
        filename = save_email_as_html(subject, sender, body)
        upload_file(filename)
        notify_update()

def run_scheduler():
    schedule.every(5).minutes.do(process_latest_email)
    while True:
        schedule.run_pending()
        time.sleep(1)

def run_gmail_script():
    run_scheduler()

# Streamlit app code
FLASK_SERVER_URL = "http://127.0.0.1:5000"

def list_saved_files():
    response = requests.get(f"{FLASK_SERVER_URL}/files")
    if response.status_code == 200:
        return response.json()
    else:
        st.error("Failed to fetch saved files")
        return []

def view_file(filename):
    response = requests.get(f"{FLASK_SERVER_URL}/view/{filename}")
    if response.status_code == 200:
        return response.text
    else:
        st.error("Failed to fetch file content")
        return ""

def remove_specific_text(html, start_marker, end_marker):
    pattern = re.compile(re.escape(start_marker) + r".*?" + re.escape(end_marker), re.DOTALL)
    return pattern.sub('', html)

def clean_html_content(html):
    html = remove_specific_text(html, "FW: The Daily Shot", "Provided for the exclusive use of zack@cliftonfirst.com")
    return html

def extract_elements_from_html(html, base_url=""):
    soup = BeautifulSoup(html, 'html.parser')
    elements = []

    def process_element(element, idx):
        if isinstance(element, Comment):
            return
        if element.name == 'img':
            img_src = urljoin(base_url, element['src'])
            elements.append(('img', img_src, idx))
        elif element.string and element.string.strip() and element.parent.name not in ['script', 'style']:
            elements.append(('text', element.string.strip(), idx))

    for idx, element in enumerate(soup.descendants):
        process_element(element, idx)

    return elements

def remove_duplicate_text(elements):
    seen_texts = set()
    unique_elements = []
    for element_type, content, idx in elements:
        if element_type == 'text':
            if content not in seen_texts:
                seen_texts.add(content)
                unique_elements.append((element_type, content, idx))
        else:
            unique_elements.append((element_type, content, idx))
    return unique_elements

def download_image(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            local_path = os.path.join("images", os.path.basename(url))
            with open(local_path, 'wb') as file:
                file.write(response.content)
            return local_path
    except Exception as e:
        st.error(f"Error downloading image {url}: {e}")
    return None

def resize_image_to_fit(image_path, max_width, max_height, text_height, note_height):
    try:
        image = Image.open(image_path)
        original_width, original_height = image.size
        aspect_ratio = original_width / original_height

        available_height = max_height - text_height - note_height - 50

        if original_width > max_width or original_height > available_height:
            if aspect_ratio > 1:
                new_width = max_width
                new_height = max_width / aspect_ratio
            else:
                new_height = available_height
                new_width = available_height * aspect_ratio
        else:
            new_width = original_width
            new_height = original_height

        resized_image = image.resize((int(new_width), int(new_height)), Image.LANCZOS)
        resized_image_path = image_path.replace(".", "_resized.")
        resized_image.save(resized_image_path)
        return resized_image_path
    except Exception as e:
        st.error(f"Error resizing image {image_path}: {e}")
        return image_path

def create_pdf_with_selected_images(selected_images):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    for img_src, relevant_text, note in selected_images:
        local_img_path = download_image(img_src)
        if local_img_path:
            text_lines = simpleSplit(relevant_text, 'Helvetica', 12, width - 100)
            note_lines = simpleSplit(note, 'Helvetica', 10, width - 100)
            
            text_height = len(text_lines) * 15
            note_height = len(note_lines) * 12

            resized_img_path = resize_image_to_fit(local_img_path, width - 100, height * 0.8, text_height, note_height)
            
            pdf.setFont("Helvetica", 12)
            text_y_position = height - 50
            for line in text_lines:
                pdf.drawString(50, text_y_position, line)
                text_y_position -= 15

            img_height = height * 0.8 - text_height - note_height - 50
            pdf.drawImage(resized_img_path, 50, text_y_position - img_height, width=width - 100, height=img_height, preserveAspectRatio=True, mask='auto')

            pdf.setFont("Helvetica", 10)
            note_y_position = text_y_position - img_height - 12
            for line in note_lines:
                pdf.drawString(50, note_y_position, line)
                note_y_position -= 12

            pdf.showPage()

    pdf.save()
    buffer.seek(0)
    return buffer

def process_html_content(html_content, base_url=""):
    cleaned_html = clean_html_content(html_content)
    elements = extract_elements_from_html(cleaned_html, base_url)
    elements = remove_duplicate_text(elements)

    st.write("### Content in the HTML document:")
    selected_images = []
    image_notes = {}
    if not os.path.exists("images"):
        os.makedirs("images")

    for i, (element_type, content, idx) in enumerate(elements):
        if element_type == 'img':
            img_tag = f'<img src="{content}" />'
            st.markdown(img_tag, unsafe_allow_html=True)
            note = st.text_input(f'Notes for image above', key=f'note_{idx}')
            if f'img_{idx}' not in st.session_state:
                st.session_state[f'img_{idx}'] = False
            selected = st.checkbox('Select Image above', key=f'img_{idx}')
            if selected:
                relevant_text = ""
                if i > 0 and elements[i-1][0] == 'text':
                    relevant_text = elements[i-1][1]
                selected_images.append((content, relevant_text, note))
            image_notes[content] = note
        elif element_type == 'text':
            st.write(content)

    if selected_images:
        pdf_buffer = create_pdf_with_selected_images(selected_images)
        st.download_button("Download PDF", pdf_buffer, "selected_images.pdf", "application/pdf")

    else:
        st.write("No images selected.")

def main():
    st.title("HTML Content Selector")

    tab1, tab2 = st.tabs(["Upload HTML", "Saved HTML Files"])

    with tab1:
        uploaded_file = st.file_uploader("Upload an HTML file", type=["html"])

        if uploaded_file is not None:
            html_content = uploaded_file.read().decode('utf-8')
            process_html_content(html_content)

    with tab2:
        saved_files = list_saved_files()
        selected_file = st.selectbox("Select a file to view", saved_files)

        if st.button("Display Selected File"):
            st.session_state['display_selected_file'] = selected_file

    if 'display_selected_file' in st.session_state:
        selected_file = st.session_state['display_selected_file']
        response = view_file(selected_file)
        if response:
            process_html_content(response, base_url="https://example.com")

if __name__ == "__main__":
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    # Start Gmail script in a separate thread
    gmail_thread = threading.Thread(target=run_gmail_script)
    gmail_thread.start()

    # Run Streamlit app
    main()
