# 📈 Trend Pulse v2

প্রতিদিন অটোমেটিক ট্রেন্ডিং টপিক সংগ্রহ করে Google Sheet-এ জমা করে — সম্পূর্ণ ফ্রি, GitHub Actions দিয়ে।

## কী কী পাবে

| বিষয় | বিবরণ |
|---|---|
| **৩টি ক্যাটেগরি (৩টি আলাদা ট্যাব)** | `Technology`, `Islamic`, `Trending (US)` |
| **৬টি প্ল্যাটফর্ম** | Google Trends, YouTube, Reddit, Google News, Bing Search, Quora |
| **প্রতি প্ল্যাটফর্মে** | প্রতিদিন ২টি করে সেরা ট্রেন্ডিং টপিক |
| **Popularity কলাম** | কত সার্চ/ভিউ/আপভোট (যেমন `500K+ searches`, `2.3M views`) |
| **AI বাছাই** | Gemini AI সবচেয়ে ট্রেন্ডিং টপিক বেছে নেয়, ডুপ্লিকেট বাদ দেয়, ক্যাটেগরিগুলো আলাদা রাখে |
| **৬০ দিন রিটেনশন** | ৬০ দিনের পুরনো রো অটোমেটিক ডিলিট হয় |
| **সময়সূচি** | প্রতিদিন সকাল ৯টা (ভারত/বাংলাদেশ সময়, 03:30 UTC) |

## শিটের কলামগুলো

`Date | Platform | Topic | Popularity (Searches/Views) | Description | Link | Source`

## ⚙️ সেটআপ (একবারই করতে হবে)

### ১. পুরনো ফাইল মুছে নতুন ফাইল দাও

রিপো থেকে **ডিলিট করো**: পুরনো `main.py`, `trendgetter`, `trend-pulse` (ফাইল দুটো অপ্রয়োজনীয়), পুরনো `.github/workflows/daily.yml`

তারপর **আপলোড করো**:
- `main.py`
- `requirements.txt`
- `.github/workflows/daily.yml`
- `README.md` (এই ফাইলটা)

### ২. GitHub Secrets চেক করো

`Settings → Secrets and variables → Actions` — এই ৪টা সিক্রেট লাগবে।
**ভালো খবর:** নিচের যেকোনো একটা নাম থাকলেই চলবে, হুবহু মেলানোর দরকার নেই:

| কীসের জন্য | যেকোনো একটা নাম হলেই হবে |
|---|---|
| সার্ভিস অ্যাকাউন্ট JSON (পুরো ফাইলের কনটেন্ট) | `GOOGLE_SHEETS_CREDENTIALS`, `GOOGLE_CREDENTIALS`, `GCP_SERVICE_ACCOUNT`, `SERVICE_ACCOUNT_JSON`, `GOOGLE_SERVICE_ACCOUNT`, `GOOGLE_SERVICE_ACCOUNT_JSON` |
| Google Sheet-এর ID | `SHEET_ID`, `SPREADSHEET_ID`, `GOOGLE_SHEET_ID`, `SHEETS_ID` |
| Gemini API key | `GEMINI_API_KEY`, `GOOGLE_GEMINI_API_KEY`, `GEMINI_KEY` |
| YouTube API key | `YOUTUBE_API_KEY`, `YT_API_KEY`, `YOUTUBE_KEY`, `GOOGLE_YOUTUBE_API_KEY` |

> 💡 Sheet ID হলো শিটের লিংকের এই অংশটা:
> `https://docs.google.com/spreadsheets/d/`**`এইটা_হলো_SHEET_ID`**`/edit`

### ৩. শিটে সার্ভিস অ্যাকাউন্টকে Editor অ্যাক্সেস দাও (সবচেয়ে জরুরি!)

আগের স্ক্রিপ্ট ফেল করার সবচেয়ে বড় কারণ সাধারণত এটাই।

1. সার্ভিস অ্যাকাউন্ট JSON ফাইলটা খোলো, `client_email` খুঁজে বের করো (দেখতে এরকম: `xxxx@xxxx.iam.gserviceaccount.com`)
2. তোমার Google Sheet খোলো → **Share** বাটন → ওই ইমেইলটা পেস্ট করো → **Editor** → Send

### ৪. চালিয়ে দেখো

`Actions` ট্যাব → **Daily Trend Fetch** → **Run workflow** → Run workflow

২–৩ মিনিটের মধ্যে শিটে ৩টা ট্যাবে ডেটা চলে আসবে। এরপর থেকে প্রতিদিন সকাল ৯টায় নিজে নিজে চলবে।

## ❓ সমস্যা হলে

- **"service-account JSON secret not found"** → ধাপ ২ দেখো, সিক্রেটের নাম তালিকার কোনোটার সাথে মেলেনি
- **"PERMISSION_DENIED" / 403** → ধাপ ৩ দেখো, শিটটা সার্ভিস অ্যাকাউন্টের সাথে শেয়ার করা হয়নি
- **YouTube-এর টপিক আসছে না** → YouTube API key সিক্রেট নেই বা Google Cloud-এ *YouTube Data API v3* enable করা নেই
- **Gemini ফেল করলে** → চিন্তা নেই, স্ক্রিপ্ট নিজেই ফলব্যাক মোডে টপিক বাছাই করে নেবে
- প্রতিটা রানের লগ `Actions` ট্যাবে দেখা যায় — কোন প্ল্যাটফর্মে কতগুলো টপিক পাওয়া গেল সব লেখা থাকে

## খরচ

সবকিছু **১০০% ফ্রি**: GitHub Actions (পাবলিক রিপোতে ফ্রি), Google Sheets API (ফ্রি), YouTube Data API (ফ্রি কোটা যথেষ্ট), Gemini API (ফ্রি টিয়ার), বাকি সব পাবলিক RSS ফিড।
