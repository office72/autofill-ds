# AUTOFILL - בוט מילוי דרכונים אוטומטי - American Docs

בוט שממלא טפסי דרכון אמריקאי (DS-11/DS-82/DS-5504) באתר הממשלתי
pptform.state.gov, מונע ע"י Google Sheet ייעודי לכל לקוח. עסק: American Docs,
עוזר ללקוחות ישראלים להגיש בקשות לדרכון אמריקאי.

## ארכיטקטורה - "מעטפת דקה + קוד שנשלף אוטומטית"

**הרעיון**: קבצי המעטפת (שכמעט אף פעם לא משתנים) מותקנים פעם אחת בכל מחשב
עובדת. הלוגיקה בפועל (`run_autofill.py`, `sheets_backend.py`) נשלפת מחדש
מהדרייב **בכל הרצה** - כך שתיקון קוד לא דורש התקנה מחדש באף מחשב.

### קבצים

| קובץ | תפקיד |
|---|---|
| `run_autofill.py` | הלוגיקה המרכזית - Selenium/undetected-chromedriver, כל שלבי האשף |
| `sheets_backend.py` | קריאה/כתיבה ל-Google Sheets + Drive (טעינת מועמדים, סטטוס, העלאת תוצאות) |
| `launcher.py` | המעטפת הדקה - שולף קוד עדכני מהדרייב ומריץ |
| `launcher_url.py` | handler ל-`passportbot://` URLs (הכפתור בשיטס פותח כזה) |
| `register_protocol.py` | רושם את `passportbot://` ב-Windows Registry (HKCU, לא צריך admin) |
| `install.bat`/`install.ps1` | התקנה חד-פעמית למחשב עובדת (Python + חבילות + רישום protocol) |
| `build_sheet.py` | הגדרת הסכמה (SECTIONS, VALIDATION_LISTS) - מקור האמת למבנה הטופס |
| `build_google_sheet_template.py` | בונה/מעדכן את תבנית ה-Google Sheet החיה מתוך build_sheet.py |
| `publish_code.py` | מעלה run_autofill.py + sheets_backend.py לתיקיית הקוד בדרייב |
| `notes.md` | תיעוד מפורט של התנהגות האתר בפועל, שלב-אחר-שלב, כולל תיקונים חיים |
| `AppsScript_Code.gs` | קוד ה-Apps Script של הכפתור "▶ הרץ" בתוך התבנית (העתק - האמת בפועל חיה בתוך הקובץ בדרייב) |

### מזהי דרייב חשובים

```
TEMPLATE_SPREADSHEET_ID = 1pfzRirYVqmI0uarzbTFWtTKTbx77wqjsMk5xGVCvVWE   # התבנית הנכונה, עם הכפתור
TEMPLATE_FOLDER_ID      = 1shwqGAVnBaPh5Pa4WKC3iGpgFM6K3jrC              # AUTOFILL_תבנית
CODE_FOLDER_ID          = 1A1w0epVQmT9C1mBIe_F1-8PuJDtWIyG4              # AUTOFILL_קוד_מערכת
MAIN_PARENT_FOLDER      = 1LsTVdtwIhP08jY0bpFrRDUMqtJEnQ1A0              # תיקיית האב - כל תיקיות הלקוחות
TEST_FOLDER             = 1MMx8EqapHwEqWdeSWsPQUlq2zyMBG-d4              # _TEST - תרחישי דמה מרובים
```

**⚠️ יש קובץ תבנית כפול שגוי**: `1pEd95KVi-97Oj0cn_YnFnG1PgtwjCMSBdvm5_7dDDew`
נוצר בטעות ב-2026-08-06 (דקה אחרי הנכון), שימש בטעות כ"התבנית" עד 2026-08-10
(אף פעם לא היה לו Apps Script בכלל!). עדיין קיים בדרייב, לא נמחק. **צריך
להחליט**: לזרוק לזבל או להשאיר. כל עותק שנוצר ממנו (כולל "אוטופיל" בתיקיית
"לוי דבורה") חסר את הכפתור - צריך להחליף אותם בעותק מהתבנית הנכונה.

### Service Account משותף

`service_account.json` (מ-`C:\Users\office_americandocs\document-analyzer\service_account.json`,
מועתק ל-AUTOFILL) - **אותו** service account כמו פרויקט document-analyzer
(`form-extractor@document-analyzer-502314.iam.gserviceaccount.com`). הוחלט
במכוון לא להקים service account נפרד - נחסך setup, אין קונפליקט הרשאות.

## איך מעדכנים (חשוב!)

| מה השתנה | מה עושים | משפיע על |
|---|---|---|
| לוגיקת בוט/תיקון באג (`run_autofill.py`, `sheets_backend.py`) | `python publish_code.py` | **מיידי** בכל מחשב עובדת, בהרצה הבאה שלו, בלי התקנה מחדש |
| סכמת השיטס (שדות, צביעה) | 1. ערוך `build_sheet.py` 2. `python build_google_sheet_template.py` | רק **עותקים חדשים** של התבנית - לקוחות קיימים לא מתעדכנים רטרואקטיבית |
| קבצי המעטפת עצמם (launcher/install/requirements) | לשלוח ZIP חדש ולהריץ `install.bat` מחדש | **נדיר** - זה בדיוק למה תוכנן ככה |
| כפתור/Apps Script בתבנית | לערוך ישירות ב-Extensions > Apps Script על קובץ התבנית | עותקים חדשים בלבד (container-bound, לא רטרואקטיבי) |

**דיבוג כשיש בעיה אצל עובדת**: הבוט מעלה screenshot+HTML לתיקיית ה-Drive
של אותו לקוח ספציפי בכישלון (`upload_debug_artifacts`), וכותב הערה ב-Status/Notes
בשיטס שלו. אפשר לחזור לכאן (השיחה עם קלוד) ולבקש לשלוף ולנתח את קבצי הדיבאג
מהדרייב - לא צריך גישה למחשב שנכשל.

## אילוצים קריטיים (מ-notes.md, אל תשכח)

- **חובה headed** (`headless=False`) - הדפדפן חייב לרוץ עם חלון נראה. גרסת
  headless נחסמת ע"י Cloudflare.
- **קצב אנושי** - פעולות מהירות מדי (בלי pause) תפסו חסימה גם ב-headed.
  יש `pause_between_fields()`, `pause_between_steps()`, `pause_between_applicants()`.
  **אף פעם לא להריץ הרבה סשנים חיים ברצף בלי הפסקות** - זה קרה כמה פעמים
  בטעות בזמן דיבוג ב-2026-08-10 (10 סשנים ברצף), עדיף להיזהר.
- **סדרתי בלבד** - אף פעם לא להריץ שני מועמדים/דפדפנים במקביל.
- **הקלדה דרך CDP** (`Input.dispatchKeyEvent`, לא `send_keys()`) - עוקף בעיית
  keyboard layout עברי שהשחית פיסוק.

## מה נעשה עד כה (סיכום, לא כרונולוגי)

1. **המרה מ-Playwright ל-Selenium** (העדפה אישית של המשתמש, לא דרישה טכנית).
2. **בוט מלא ועובד** לכל התרחישים: First-time, Have Book (renewal, עם/בלי
   שדרוג ל-DS-11), Book Lost/Stolen (כולל דוח אבדה מלא + DS-64), Limited
   Validity (DS-5504), מבוגר וילד.
3. **ארכיטקטורת production מלאה**: תבנית → עותק ללקוח → כפתור בשיטס מריץ
   מקומית → קוד מתעדכן אוטומטית → תוצאה חוזרת לדרייב → עמידות לכשלים
   per-applicant (לא עוצר תור שלם).
4. **מתקין** (`install.bat`) שמתקין Python אמיתי + חבילות (לא PyInstaller
   מלא - selenium/undetected-chromedriver קשים מדי לארוז).
5. **תבנית שיטס עם UX משופר** (2026-08-09/10):
   - פאנל "KEY QUESTIONS" בראש הגיליון (Date of Birth, Passport Scenario,
     Book Issue Date) - הועברו לשם *ולא* משוכפלים מהמקום הישן.
   - צביעה דינמית (DYN) מלאה מבוססת על **כללי הזכאות הרשמיים** של
     DS-11/DS-82/DS-5504 (נקראו ישירות מטפסי המדינה, לא ניחוש) - נוסחאות
     Google Sheets עם `IFERROR` (קריטי - `OR`/`AND` בשיטס לא מתעצלים,
     `DATEDIF` על תא ריק זורק שגיאה שהורסת את כל הנוסחה בלי ה-wrap).
   - שדות "Name Change" (Type/Place/Date/Certified Docs) - כולל שדה
     "Certified Docs" שהתגלה רק ב-2026-08-10 והוא בדיוק הקריטריון
     שקובע DS-82 מול DS-11.
6. **מספר באגים אמיתיים באתר עצמו שהתגלו ותוקנו ב-2026-08-10** (ראה
   `notes.md` לפרטים מלאים):
   - עמוד "בחירת מוצר" (Book/Card/Both/First-time) נפרד מעמוד "מצב הספר" -
     לא נפתח אוטומטית ב-AJAX כמו רוב השאלות.
   - "הנתונים הודפסו נכון" ו"השם השתנה" הן שאלות בלתי-תלויות - בדיקת
     הנוכחות של כל השלב הייתה שגויה (גייטה הכל לפי פאנל אחד בלבד).
   - IDs אמיתיים של פאנל שינוי-השם שונים מהניחוש הראשוני.
   - EC Email חובה באתר בפועל (היה מסומן כלא-חובה אצלנו).
   - Stale element ב-Step 2 (Address) - נוסף retry גנרי.
7. **באג EC Phone שנפתר סופית**: מספר טלפון עם "+" בהתחלה (למשל
   "+972-50-1234567") מתפרש ע"י **Google Sheets עצמו** כנוסחה אריתמטית
   (972-50-1234567 = -1233645!) - לא קשור לאתר/לקוד בכלל. עיצוב תא כ-Plain
   Text לא פותר את זה. הפתרון: `_validate_applicant_data()` ב-`run_autofill.py`
   בודק לפני פתיחת דפדפן אם שדה ספרתי חזר כמספר שלילי, וזורק שגיאה ברורה.
8. **גילוי קריטי על התבנית עצמה**: הקובץ שהיה מוגדר כ"התבנית" מעולם לא
   היה לו Apps Script מחובר (עותק כפול שגוי מ-2026-08-06). אותר, שוחזר קובץ
   מקורי מהזבל - **גם הוא** התברר כריק. נכתב מחדש `AppsScript_Code.gs`
   (תפריט "AUTOFILL" עם כפתור "▶ הרץ") ואומת שעובד.
9. **חבילת התקנה** ל-ZIP (`AmericanDocsAutofill_Installer.zip`) עם README.

## מה בתהליך / הצעד הבא

**אינטגרציית Zoho ל"לקוח חדש"** - עדיין לא התחיל בפועל, רק תוכנן:

- המטרה: כפתור **בזוהו** (לא רק בשיטס) שלוקח את קישור תיקיית הלקוח (שדה
  URL מותאם-אישית בעסקה) ומעתיק אליו את תבנית ה-AUTOFILL אוטומטית.
- **התגלה**: כבר יש תשתית-גישור עובדת ומוכחת בפרויקט האחר,
  `C:\Users\office_americandocs\document-analyzer` - שירות Cloud Run ציבורי
  (`trigger_service.py`, GCP project `document-analyzer-502314`,
  region `me-west1`, URL: `https://trigger-service-826386462532.me-west1.run.app/trigger`)
  שזוהו כבר קורא לו בהצלחה, מוגן ב-shared secret (header `X-Trigger-Secret`,
  לא IAM כי Deluge לא חותם טוקן גוגל), עם אותו service account.
- **התוכנית**: להוסיף route/ענף לוגיקה חדש לאותו `trigger_service.py` הקיים
  (לא להקים תשתית נפרדת) - מקבל `{action: "new_autofill_client", client_name, folder_link, secret}`,
  מעתיק את התבנית הנכונה (`1pfzRirYVqmI0uarzbTFWtTKTbx77wqjsMk5xGVCvVWE`)
  לתיקיית הלקוח, מחזיר קישור. פריסה מחדש דרך `cloudbuild.trigger.yaml` הקיים.
  ואז: קוד Deluge קצר לכפתור חדש בזוהו.
- **טרם אושר לביצוע** - המתנתי לאישור המשתמש להתחיל לגעת ב-production
  cloud service שפרויקט אחר (document-analyzer) תלוי בו.
- **חלופה פשוטה יותר שכבר מוכנה כרעיון** (לא ממומשת): כפתור שני בתוך
  תפריט "AUTOFILL" בתבנית עצמה ("➕ לקוח חדש") - מבקש שם, יוצר תיקייה +
  מעתיק תבנית + מחזיר קישור, בלי לגעת בזוהו/בענן בכלל. פחות "אלגנטי"
  (לא מתחיל מתוך זוהו) אבל אפס תשתית נוספת.

## פריטים פתוחים נוספים

- להחליט על גורל התבנית הכפולה השגויה (`1pEd95KVi...`) - לזרוק או להשאיר.
- להחליף את העותק "אוטופיל" (בתיקיית "לוי דבורה") בעותק מהתבנית הנכונה.
- להפיץ את `AmericanDocsAutofill_Installer.zip` למחשבי עובדות נוספים (נבנה,
  טרם הופץ/נבדק במחשב שני מלבד המחשב שכבר הותקן).
- Workspace Admin Console API trust - כדי לבטל את מסך "Authorization
  required" בכל עותק חדש (נדחה ע"י המשתמש, "בהמשך תלמד אותי").
- `select_option()` ב-`run_autofill.py` לא קיבל את אותה הגנת stale-element
  retry כמו `check()`/`fill_text()` (הוחלט במכוון לא לגעת, לא היה מעורב
  בכשל שנצפה - לשקול בעתיד אם יופיע כשל דומה שם).

## הערה על git

הריפו הזה **לא** היה תחת git עד 2026-08-11. אותחל עכשיו, מקומי בלבד
(לא נדחף לשום remote). `.gitignore` מוציא: `service_account.json` (סוד),
`debug/`+`downloaded_pdfs/`+`bot_runtime/` (PII של לקוחות אמיתיים/פלטי
ריצה), קבצי HTML גולמיים מהחקירה הראשונית של האתר, וקבצים גנרטיביים
(`Applications.xlsx`, ה-ZIP של המתקין).
