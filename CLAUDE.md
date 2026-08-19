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

## כפתור "לקוח חדש" בזוהו - עובד ב-production (הושלם 2026-08-11/12)

כפתור מותאם ב-Zoho CRM (מודול Deals) יוצר עותק שיטס AUTOFILL אוטומטית
בתיקיית הלקוח, ע"י קריאה ל-route חדש (`/new_autofill_client`) שנוסף
לשירות ה-Cloud Run הקיים והמשותף `trigger-service` (בפרויקט האחר,
`document-analyzer`, GCP project `document-analyzer-502314`,
region `me-west1`) - לא הוקמה תשתית נפרדת.

**תגלית קריטית שעיצבה את הפתרון**: Apps Script **מסרב להריץ סקריפט קשור
(bound) שקובץ הקונטיינר שלו נוצר ע"י service account** - לא בעיית
הרשאות/מסך הסכמה, חסימה קשיחה. גם לא ניתן לתקן בהעברת בעלות בדיעבד
(לקבצים בתוך Shared Drive אין בכלל מושג "בעלים" per-file). **הפתרון**:
ההעתקה מתבצעת "בתור" בן-אדם אמיתי בוורקספייס (office@americandocs.co.il),
לא ה-service account המשותף - נבחר **OAuth refresh token** מצומצם-scope
(Drive בלבד) על פני domain-wide delegation, כדי לצמצם נזק פוטנציאלי אם
`service_account.json` (יושב כקובץ רגיל בשתי תיקיות מקומיות) ידלוף אי-פעם.

פרטים מלאים (סודות ב-GCP Secret Manager, שם ה-revision, קוד ה-Deluge)
נשמרים בזיכרון השיחה (`project_autofill_bot.md`) ולא כאן, כי הם חיים
בפרויקט האחר.

## צינור קליטת מסמכי לקוח חדש - AI Intake (הושלם 2026-08-13)

**קובץ נפרד לגמרי**: `extract_client_intake.py` - **במכוון בלי שום import
או קשר קוד ל-`run_autofill.py`** - הדבר היחיד שהם חולקים הוא השיטס עצמו,
דרך עמודת Status (`Needs Review` -> עובדת בודקת -> `Ready` -> הבוט הדטרמיניסטי
יכול לרוץ). הפעלה ידנית בלבד, אף פעם לא אוטומטית.

שלוש פונקציות חילוץ עצמאיות, כל אחת נבדקה בנפרד על מסמכי לקוח אמיתיים:

| שלב | מודל | קלט | הערות |
|---|---|---|---|
| `extract_fillout_data()` | Sonnet 5 | טקסט ייצוא Google Doc של Fillout | לא שואל Sex/Country of Birth בכלל - הטופס לא נותן להם מקור אמיתי, אלו מגיעים מהמסמכים |
| `extract_passport_data()` | Opus 5 (ראייה) | תמונת/סריקת עמוד הביו של דרכון | כולל גם שדות "MOST RECENT PASSPORT" (Book Number וכו') - צילום דרכון קודם *הוא* המקור לשדות האלו |
| `extract_birth_cert_data()` | Opus 5 (ראייה, PDF) | תעודת לידה דו-לשונית (משרד הפנים) | קורא את העמודה **האנגלית הרשמית** המודפסת על התעודה עצמה, לא מתעתק מחדש מעברית - עדיפות לאיות רשמי קיים על פני תעתוק טרי |

**כלל מיזוג** כשיש כמה מקורות לאותו לקוח: Fillout ראשון, תעודת לידה
דורסת אותו על שדות חופפים (מסמך רשמי > דיווח עצמי בטופס), ודרכון דורס את
שניהם (הכי קרוב למה שכבר יש למחלקת המדינה על הלקוח בחידוש). אומת חי:
"Ilay"/"Ben Simon" המתועתק מ-Fillout נדרס נכון ל-"ELY"/"BEN-SIMON" המודפס
בדרכון.

**כתיבה לשיטס** (`write_applicant_data()`, subcommand `build`): טאב
"Applicants" **הפוך** - עמודה A = תוויות שדות (מקובצות לפי מקטעים
צבועים), שורה 1 = כותרות "Applicant 1"/"Applicant 2"/... (אחים חולקים
קובץ אחד, עמודה לכל אחד), כל נתוני מועמד אחד יושבים בעמודה אחת. הכתיבה
משתמשת ב-`valueInputOption="RAW"` **ולא** `"USER_ENTERED"` - במכוון,
כי USER_ENTERED גורם לשיטס "לפרש" טקסט כנוסחה/תאריך לפי locale - בדיוק
מה שגרם לשני באגים אמיתיים אחרים בפרויקט (טלפון עם "+" שהתפרש כחשבון
אריתמטי; תאריכי DD/MM מול MM/DD דו-משמעיים). קובעת גם `Status = "Needs Review"`
בסוף. נבדק חי מקצה-לקצה על עותק אמיתי בתיקיית `_TEST`.

**`scan` - איתור אוטומטי מלא + כפתור בזוהו (הושלם 2026-08-13)**:
`scan_and_build()` סורק תיקיית לקוח שלמה, מסווגת כל קובץ תמונה/PDF בקריאת
Sonnet זולה אחת (`classify_document()` - PASSPORT / ISRAELI_BIRTH_CERTIFICATE /
CITIZENSHIP_EVIDENCE / OTHER), מריצה את שלב החילוץ היקר (Opus) רק על מה
שסווג בפועל, מקבצת לפי (שם פרטי, שם משפחה) שנקרא **מתוך המסמכים עצמם** -
קבוצה אחת לכל ילד/מועמד - וכותבת כל קבוצה לעמודת Applicant נפרדת (1, 2,
3...) לפי סדר הופעה. משנה שם קבצים בדרייב ל-`"{סוג} - {שם}"` (למשל
`"Passport - NAVE PELTER.jpeg"`). **את השיטס עצמו היא מוצאת לבד בתיקייה**
(`find_client_sheet()` - מחפש קובץ יחיד מסוג Google Sheet בתיקייה וזורק
שגיאה ברורה שעוצרת הכל אם אין בדיוק אחד) - אין צורך למסור/לשמור קישור
שיטס בזוהו בכלל, לפי החלטת המשתמש ("בתוך תיקיית הלקוח יהיה רק שיטס אחד").

**מסמך שלישי נתמך**: `extract_citizenship_evidence_data()` - תעודת
אזרחות/התאזרחות (USCIS), CRBA (Consular Report of Birth Abroad, טופס
FS-240), או תעודת לידה אמריקאית - שלושתם מקובצים לחילוץ אחד כי בשיטס אין
שדה ייחודי לאף אחד מהם חוץ מ-USCIS A-Number.

**סדר עדיפויות במיזוג** (חלש לחזק, כל `.update()` דורס את הקודם): Fillout
(דיווח עצמי) < תעודת לידה ישראלית (מקור מקורי, לא קשור לאיות האנגלי אצל
ממשלת ארה"ב) < מסמך אזרחות אמריקאי (**זה** האיות הרשמי הרשום בפועל אצל
ממשלת ארה"ב) < דרכון (הכי קרוב למה שכבר יש למחלקת המדינה, קריטי בחידוש).

**שיתוף שדות משפחתיים בין אחים** (`SHARED_FAMILY_FIELDS`/`_fill_shared_family_fields`) -
כתובת/איש קשר לחירום/הורים/טיול מועתקים בין אחים מאותה תיקייה אם חסרים
לאחד ויש לשני, לפי בקשת המשתמש - **אף פעם** לא שדות זהות אישיים.

**באג אמיתי שנמצא בבדיקה חיה מול השירות בענן** (לא נראה בבדיקות מקומיות
קודמות): סיווג לא-דטרמיניסטי - קובץ טופס DS-11 מלא (`טופס נווה פלטר.pdf`)
סווג פעם אחת כ-PASSPORT (מסמך DS-11 מלא נראה חזותית דומה לדרכון - שדות
נתונים+תמונה). זה יצר "מועמד רפאים" בעמודה עם שם ריק, וגם **שינה בפועל את
שם הקובץ האמיתי** ל-"Passport -  .pdf" בתיקיית לקוח אמיתית - תוקן ידנית
בחזרה. שני תיקונים: (1) `classify_document()` הועבר מ-Haiku ל-Sonnet
(אותו תיקון-אמינות שכבר נעשה לתעתוק Fillout), (2) הגנה נוספת ברמת הקוד -
קבוצה עם שם ריק (`("", "")`) נמחקת מיד ולעולם לא נכתבת/משנה שם קובץ, בלי
קשר לאיזה מודל משמש לסיווג. אומת אחרי התיקון: שני רצים חוזרים על אותה
תיקייה בפועל, בלי מועמד-רפאים.

**פריסה כשירות Cloud Run נפרד** (`autofill-intake-service`, לא נוגע
ב-`trigger-service` הקיים) - קבצים: `intake_service.py` (עטיפת Flask סביב
`scan_and_build`), `Dockerfile.intake`, `requirements-intake.txt`,
`cloudbuild.intake.yaml`, `.gcloudignore` (**קריטי** - בלי זה
`gcloud builds submit` היה מעלה את כל התיקייה כולל `service_account.json`/
`.env`/PII של לקוחות אמיתיים; אומת עם `gcloud meta list-files-for-upload`
שרק 4 הקבצים הדרושים עולים בפועל).
- **gcloud CLI זמין עכשיו מקומית** במחשב הזה (`C:\Users\office_americandocs\AppData\Local\Google\Cloud SDK`) -
  אין יותר צורך ב-Cloud Shell להעלאות/פריסות רגילות. חשבון ברירת המחדל
  המוגדר הוא חשבון-השירות `form-extractor@...` (`gcloud config set account`) -
  לפעולות שדורשות בן-אדם אמיתי (כמו `add-iam-policy-binding` על שירות
  Cloud Run - חשבון-שירות לא יכול לתת הרשאות IAM לעצמו, אותה בעיה כמו
  קודם) יש להתחבר זמנית עם `gcloud auth login --account=office@americandocs.co.il`
  (פותח דפדפן על המחשב עצמו - הרבה יותר פשוט מהריקוד ב-Cloud Shell), ואז
  לחזור ל-`gcloud config set account form-extractor@...`.
- **אימות ל-Drive/Sheets ב-Cloud Run בלי קובץ מפתח בכלל**: `_get_credentials()`
  ב-`extract_client_intake.py` בודקת אם `service_account.json` קיים
  מקומית (מחשב עובדת/CLI) - אם לא, נופלת ל-`google.auth.default()`
  (Application Default Credentials) שמזהה אוטומטית את חשבון-השירות המצורף
  לשירות ה-Cloud Run (`--service-account=form-extractor@...` בפריסה) -
  אותו חשבון-שירות בדיוק, בלי לנהל/למונטג' סוד קובץ-מפתח כלל בענן.
- **סודות ב-Secret Manager**: `anthropic-api-key` (כבר קיים, משותף עם
  extraction-job), `autofill-intake-shared-secret` (חדש - הסוד שכפתור
  הזוהו שולח בכותרת/פרמטר `secret`).
- **כתובת השירות**: `https://autofill-intake-service-826386462532.me-west1.run.app/scan_client_documents` -
  POST עם `{folder_id, secret}` בלבד (JSON או form-encoded, שני הפורמטים
  נתמכים כמו ב-route הקיים). `timeout` גבוה (600 שנייה, גם ב-gunicorn וגם
  בפריסת Cloud Run) כי סריקת תיקייה עם כמה מסמכים מריצה כמה קריאות Opus
  ברצף. פריסה מחדש: `gcloud builds submit --config cloudbuild.intake.yaml .`
  ואז `gcloud run deploy autofill-intake-service --image=... --region=me-west1
  --service-account=form-extractor@document-analyzer-502314.iam.gserviceaccount.com
  --set-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest,INTAKE_SHARED_SECRET=autofill-intake-shared-secret:latest
  --timeout=600 --memory=512Mi`.
- קוד ה-Deluge לכפתור השני ("סרוק מסמכים") נשמר ב-`zoho_scan_documents_button.deluge` -
  קורא ל-route הזה עם `folder_id` בלבד מתוך שדה `Test` של הדיל. **הוגדר
  ופועל בזוהו בפועל** (2026-08-14) - הפונקציה חייבת קטגוריה `button`
  (נקבעת ע"י העורך עצמו, לא שרירותית) וסוג החזרה `string` (לא `void`) -
  המחרוזת המוחזרת היא ההודעה שמוצגת למשתמש. בניית ה-parameters map
  ל-`invokeurl` חייבת להיות כמשתנה נפרד (`paramMap = Map(); paramMap.put(...)`) -
  map literal מוטבע ישירות בתוך בלוק ה-`invokeurl` גרם לשגיאת syntax.

**⚠️ באג קריטי שנתפס בשימוש חי ראשון (2026-08-14) - חובה לזכור**: כל
גיליון AUTOFILL אמיתי ללקוח **חייב** להיווצר דרך ה-route `/new_autofill_client`
(OAuth, "בתור" office@) - **לעולם לא** ע"י `drive.files().copy()` ישיר דרך
חשבון-השירות (`get_drive_service()` ב-`extract_client_intake.py`). עותק
שנוצר ישירות ע"י חשבון-השירות משחזר בדיוק את בעיית "Apps Script מסרב
לרוץ על קובץ שנוצר ע"י חשבון-שירות" - התפריט/כפתור "▶ הרץ" פשוט לא עובד.
זה קרה בפועל על גיליון לקוח אמיתי (גיא ארם) - המשתמש שם לב שהכפתור חסר,
תוקן ע"י יצירת עותק נכון דרך ה-route הקיים והעברת הנתונים (`spreadsheets().values().get`/`update`
על עמודה B) מהגיליון השבור לחדש, בלי להריץ מחדש את כל שלב החילוץ.
עותקים ישירים דרך חשבון-השירות מותרים **רק** לתיקיית `_TEST` (בדיקות
בלבד, אף אחד לא באמת ילחץ שם על הכפתור).

**ממצא נלווה**: חשבון-השירות יכול `trashed: true` (מחיקה רכה) קובץ ב-Shared
Drive הזה, אבל `files().delete()` ישיר על אותו קובץ מחזיר 404 (כנראה
פער הרשאות content-manager מול manager) - להשתמש ב-trash, לא ב-delete.

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
- מנגנון הפעלה ל-`extract_client_intake.py build` - ראה למעלה.

## הערה על git

הריפו הזה **לא** היה תחת git עד 2026-08-11. אותחל עכשיו, מקומי בלבד
(לא נדחף לשום remote). `.gitignore` מוציא: `service_account.json` (סוד),
`debug/`+`downloaded_pdfs/`+`bot_runtime/` (PII של לקוחות אמיתיים/פלטי
ריצה), קבצי HTML גולמיים מהחקירה הראשונית של האתר, וקבצים גנרטיביים
(`Applications.xlsx`, ה-ZIP של המתקין).
