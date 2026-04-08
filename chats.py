from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import re
from wordcloud import WordCloud
import base64
from io import BytesIO
import emoji
import matplotlib
matplotlib.use('Agg')   # ✅ MUST ADD
import matplotlib.pyplot as plt
from collections import Counter

app = Flask(__name__)
CORS(app)

df = None  # global dataframe


# ✅ PREPROCESS FUNCTION
def preprocess(chat_data):
    data = []

    messages = chat_data.split('\n')

    for msg in messages:
        msg = msg.strip()
        if not msg:
            continue

        match = re.match(
            r'^(\[?\d{1,2}[/-]\d{1,2}[/-]\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s?(?:[apAP][mM])?\]?)\s[-]?\s([^:]+):\s(.+)',
            msg
        )

        if match:
            date, user, message = match.groups()
            data.append([date.strip("[] "), user.strip(), message.strip()])

    df_local = pd.DataFrame(data, columns=['messages_date', 'users', 'messages'])

    df_local['messages_date'] = pd.to_datetime(
        df_local['messages_date'],
        dayfirst=True,
        errors='coerce'
    )

    df_local = df_local[df_local['messages_date'].notna()]

    df_local['year'] = df_local['messages_date'].dt.year
    df_local['month'] = df_local['messages_date'].dt.month_name()
    df_local['day'] = df_local['messages_date'].dt.day
    df_local['hour'] = df_local['messages_date'].dt.hour
    df_local['minute'] = df_local['messages_date'].dt.minute

    df_local['messages_date'] = df_local['messages_date'].astype(str)

    return df_local

def get_most_common_words(df, selected_user):
    
    # filter user
    if selected_user != "Overall":
        df = df[df['users'] == selected_user]

    words = []

    # load stopwords
    with open('stopwords.txt', 'r') as f:
        stopwords = f.read().split()

    for message in df['messages']:
        if not message:
            continue

        # ❌ skip media
        if 'media omitted' in message.lower():
            continue

        # ✅ clean text
        message = re.sub(r'[^\w\s]', '', message)

        for word in message.lower().split():
            if word not in stopwords and len(word) > 2:
                words.append(word)

    # 🔥 DEBUG
    print("Total words collected:", len(words))

    return Counter(words).most_common(20)

def extract_emojis(text):
    return [char for char in text if char in emoji.EMOJI_DATA]

def emoji_stats(df, selected_user):
    if selected_user != "Overall":
        df = df[df['users'] == selected_user]

    emojis = []
    for message in df['messages']:
        emojis.extend(extract_emojis(message))

    emoji_count = Counter(emojis)

    return dict(emoji_count) 
# ✅ UPLOAD ROUTE
@app.route('/upload', methods=['POST'])
def upload():
    global df

    file = request.files['file']
    chat_data = file.read().decode('utf-8')

    df = preprocess(chat_data)

    users = df['users'].unique().tolist()

    return jsonify({
        "data": df.to_dict(orient="records"),
        "users": users
    })


# ✅ ANALYZE ROUTE
@app.route('/analyze', methods=['POST'])
def analyze():
    global df

    data = request.get_json()

    if df is None:
        return jsonify({"error": "Upload file first"}), 400

    user = data.get('user')

    temp_df = df.copy()

    if user != "Overall":
        temp_df = temp_df[temp_df['users'] == user]

    # ✅ BASIC STATS
    total_messages = temp_df.shape[0]
    total_words = temp_df['messages'].apply(lambda x: len(str(x).split())).sum()
    media_messages = temp_df[temp_df['messages'].str.contains('<Media omitted>', na=False)].shape[0]

    # ✅ LINKS
    url_pattern = r'(https?://\S+|www\.\S+)'
    links = []

    for msg in temp_df['messages']:
        found = re.findall(url_pattern, str(msg))
        links.extend(found)

    total_links = len(links)

    # ✅ TOP USERS
    user_counts = temp_df['users'].value_counts()

    percent_df = ((user_counts / temp_df.shape[0]) * 100).round(2).reset_index()
    percent_df.columns = ['user', 'percent']

    user_percent_list = percent_df.to_dict(orient='records')

    top_users = user_counts.head(5).index.tolist()
    top_counts = user_counts.head(5).values.tolist()
    top_percent = percent_df['percent'].head(5).tolist()

    # ✅ WORDCLOUD
    wc_df = temp_df.copy()

    wc_df = wc_df[~wc_df['messages'].str.contains('<Media omitted>', na=False)]
    wc_df['messages'] = wc_df['messages'].str.replace(url_pattern, '', regex=True)

    text = " ".join(wc_df['messages'].dropna())

    wordcloud_base64 = None

    if text.strip() != "":
        wc = WordCloud(width=600, height=300, background_color='white').generate(text)

        img = BytesIO()
        plt.imshow(wc)
        plt.axis('off')
        plt.tight_layout()
        plt.savefig(img, format='png')
        plt.close()
        img.seek(0)

        wordcloud_base64 = base64.b64encode(img.getvalue()).decode()

    # ✅ FIXED: ALWAYS compute common words
    common_words = get_most_common_words(temp_df, user)

    print("COMMON WORDS:", common_words[:5])  # debug

    return jsonify({
        "total_messages": int(total_messages),
        "total_words": int(total_words),
        "media_messages": int(media_messages),
        "total_links": int(total_links),
        "links": links[:20],

        "top_users": top_users,
        "top_counts": top_counts,
        "top_percent": top_percent,
        "user_percent": user_percent_list,

        "wordcloud": wordcloud_base64,
        "common_words": common_words   # ✅ now correct
    })
@app.route('/emoji-stats', methods=['POST'])
def emoji_stats_api():
    data = request.json
    selected_user = data.get('user')

    result = emoji_stats(df, selected_user)

    return jsonify(result)
@app.route('/timeline', methods=['POST'])
def timeline():
    data = request.get_json()
    user = data.get("user")

    df_local = df.copy()

    # 🔹 Filter user
    if user != "Overall":
        df_local = df_local[df_local['users'] == user]

    # 🔹 FIX: force datetime (IMPORTANT)
    df_local['messages_date'] = pd.to_datetime(
        df_local['messages_date'], errors='coerce'
    )

    # 🔹 remove null dates (IMPORTANT)
    df_local = df_local.dropna(subset=['messages_date'])

    # 🔹 Monthly
    df_local['year'] = df_local['messages_date'].dt.year
    df_local['month_num'] = df_local['messages_date'].dt.month
    df_local['month'] = df_local['messages_date'].dt.strftime('%b')

    monthly = df_local.groupby(
        ['year', 'month_num', 'month']
    ).count()['messages'].reset_index()

    monthly['time'] = monthly['month'] + "-" + monthly['year'].astype(str)
    monthly = monthly[['time', 'messages']]

    # 🔹 Daily (FIXED)
    df_local['only_date'] = df_local['messages_date'].dt.date

    daily = df_local.groupby('only_date').count()['messages'].reset_index()

    # 🔹 Return
    return jsonify({
        "monthly_timeline": monthly.to_dict(orient='records'),
        "daily_timeline": daily.to_dict(orient='records')
    })
if __name__ == "__main__":
    app.run(debug=True)