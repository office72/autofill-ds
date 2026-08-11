# AUTOFILL - כללים והערות למילוי הטופס

## שלב 1 - About You (זהה בכל הטפסים: DS-11 / DS-82 / DS-5504)

- **State/Territory of Birth**: לא נדרש שדה בשיטס אם ה-Country of Birth אינו ארה"ב. השדה הזה באתר מופיע ונדרש רק כאשר Country of Birth = UNITED STATES.
- **SSN**: אם ללקוח אין מספר ביטוח לאומי אמריקאי (SSN), יש להזין אפסים (000000000) במקום להשאיר ריק.

## שלב 2 - Address / GEN (זהה בכל הטפסים)

**כתובת למשלוח (Mailing Address):** Street, City, Country, State, Zip, In Care Of (לא חובה).
- **State (mailStateList)**: לא נדרש בשיטס אם Country (mailCountryList) אינו ארה"ב - אותו כלל בדיוק כמו ב-State of Birth בשלב 1.

**"Is This Your Permanent Address?"** (Yes/No, חובה):
- אם **No** - נפתח בלוק נוסף "Permanent Address": Street, Apartment/Unit, City, Country, State, Zip - עם אותו כלל: State לא נדרש אם Country אינו ארה"ב.
- אם **Yes** - כנראה שהבלוק הנוסף לא נפתח בכלל (הכתובת הקבועה = כתובת המשלוח). **צריך אימות**: לשמור גם גרסה עם "Yes" מסומן כדי לוודא שבאמת לא נפתח שום דבר נוסף.

**Preferred Method of Communication** (Mail / Email / Both, חובה) + Email Address + Confirm Email Address.
- **לא ברור אם שדות האימייל מופיעים/נדרשים תמיד או רק כשבוחרים Email/Both** - צריך גרסה עם "Mail" מסומן לבד כדי לבדוק אם שדה האימייל נעלם/מפסיק להיות חובה.

## שלב 3 - Emergency Contact (זהה בכל הטפסים)

שדות: Name, Address, Apartment, City, Country, State, Zip, Phone, Email, Relationship.
- **State (ecStateList)**: לא נדרש בשיטס אם Country (ecCountryList) אינו ארה"ב - אותו כלל בדיוק כמו בשלבים הקודמים.

## שלב 4 - Your Most Recent Passport (זהה בכל הטפסים)

**עדכון 2026-08-10, מאומת חי**: "Select the option that best describes your situation" (Book/Card/Both/First-time) הוא עמוד/פאנל **נפרד** - השאלה הבאה ("Do you still have your book...") **לא** נפתחת אוטומטית ב-AJAX על אותו עמוד אחרי הבחירה כמו רוב שאר השאלות ה-radio באשף הזה; היא מופיעה רק אחרי לחיצת Next נוספת. הקוד (`step_most_recent_passport`) עודכן להיות אדפטיבי: בודק אם `BookYes` (וכו') כבר קיים ב-DOM לפני שהוא לוחץ Next שוב.

שאלה ראשונה (חובה, קובעת מה נפתח בהמשך): "Select the option that best describes your situation":
- Have a passport book and want to renew or replace it (CurrentHaveBook)
- Have a passport card and want to renew or replace it (CurrentHaveCard)
- Have both a book and card... (CurrentHaveBoth)
- First-time applicant, or do not want to submit most recent passport (CurrentHaveNone)

**חסר**: הקובץ שנשמר לא כלל אף בחירה מסומנת, ולכן לא רואים אילו שדות נוספים (מספר דרכון קודם, תאריך הנפקה וכו') נפתחים עבור Book/Card/Both. אם הלקוחות של העסק הם בעיקר first-timers (DS-11), ייתכן שמספיק לתעד רק את CurrentHaveNone (שכנראה לא פותח שום שדה נוסף). אם יש גם מקרים של חידוש (DS-82) צריך לשמור גרסה נפרדת לכל אחת מהאופציות Book/Card/Both כדי לתפוס את השדות שנפתחים.

**החלטה עסקית**: העסק אף פעם לא מטפל ב-Passport Card (רק Book), אז אופציות 2 (Card) ו-3 (Both) לא רלוונטיות ולא צריך לתעד אותן. ממפים רק אופציה 1 (Book) ואופציה 4 (First-time applicant).

### תת-מסלול "Have a passport book" (קובץ 5-1.html = Book + Lost)

שאלה: "Do you still have your book in your possession?" - 4 אופציות: Yes (BookYes) / Yes אבל ניזוק (BookDamaged) / No, אבד (BookLost) / No, נגנב (BookStolen).

- **אם Lost או Stolen**: נפתחת שאלה משותפת (זהה לשתיהן) "Have you reported your lost or stolen book?" - Yes/No.
- **בהמשך:**
  - תאריך הנפקת הדרכון האחרון (BookIssueDate, MM/DD/YYYY) - **תיקון**: אין שאלת "הונפק לפני יותר מ-15 שנה" בפועל (למרות שיש קוד כזה מוסתר ב-HTML) - יש רק שנת/תאריך הנפקה. בהתאם לשנה הזו ייתכן שינוי בהמשך התהליך - **עדיין לא ברור, נחזור לזה בהמשך, אל תניח כלום עד אז**.
  - שם כפי שמופיע בדרכון הקודם: First+Middle Name, Last Name
  - מספר הדרכון הקודם (Book Number)

## שלב 6 - Most Recent Passport (המשך) - mostRecentPassportContinued (זהה לכולם)

שתי שאלות חובה:
1. **"Was the data printed incorrectly in your most recent document?"** (כן/לא). אם **כן** (המידע שגוי) - נפתחת רשימת checkboxes לבחירת אילו שדות שגויים: Last Name, First Name, Middle Name, Place of Birth, Date of Birth, Sex (אפשר לסמן כמה שרוצים).
2. **"Has your name changed since your most recent document was issued?"** (כן/לא).

**כלל עסקי קריטי**: אם המידע שגוי (ולא ניתן לתיקון), או שהיה שינוי שם שלא ניתן להוכיח עם מסמכים - **הטופס הנכון הופך ל-DS-11** (ולא ממשיכים בתהליך "דרכון קיים"/DS-82 הרגיל).

**עדכון 2026-08-10, מאומת חי (תרחיש DS-82 מלא: מבוגר, ספר הונפק ~12 שנה, שינוי שם בבית משפט, ספר ברשות)**: כשעונים "כן" ל-"Has your name changed", נפתח פאנל עם **4** שדות (לא 3 כמו שהונח קודם) - תואם ל-DS-82 Application Page 1 סעיף 11 "Name Change Information", אבל עם שאלה נוספת שלא הייתה בטופס הנייר:
- **Reason for the name change?** - radio: Marriage / Court Order. ID אמיתי: `NameChangeReason_0` (Marriage, value="M") / `NameChangeReason_1` (Court Order, value="C") - **לא** `ChangedByMarriage`/`ChangedByCourtOrder` כמו שנוחש קודם.
- **Date of name change (MM/DD/YYYY)?** - textbox, ID אמיתי: `NameChangeDate` - **לא** `DateOfNameChangeTextBox`.
- **Place of name change (City/State)?** - textbox, ID אמיתי: `NameChangePlace` - **לא** `PlaceOfNameChangeTextBox`.
- **Can you submit certified documentation to reflect the name change?** (Yes/No) - שדה **חדש שלא ידענו עליו כלל**. ID: `NameChangeCertified_0` (Yes) / `NameChangeCertified_1` (No). זה בדיוק הקריטריון מה-DS-82 שקובע DS-82 מול DS-11 ("...and I can submit proper certified documentation..."). נוסף שדה מתאים בשיטס (`Name Change Certified Docs?`) ונכלל בנוסחת ה-DS11_required (No = מחייב DS-11).

כל 4 השדות מופיעים יחד באותו פאנל (AJAX, לא עמוד נפרד) מיד אחרי בחירת "Yes, it has changed". הקוד ב-`step_most_recent_passport_continued_if_present` תוקן עם ה-IDs האמיתיים. גם התגלה ש**"Has your name changed" ו-"Was the data printed incorrectly" הן שאלות בלתי-תלויות** - בריצה אחת הופיעה רק שאלת השם-השתנה בלי שאלת הנתונים-שגויים בכלל, אז הבדיקה "האם השלב הזה בכלל מופיע" חייבת לבדוק את שתיהן בנפרד (לא לגייט את כל השלב לפי `DataIncorrectButtonsPanel` בלבד כמו שהיה קודם - זה דילג על כל השלב כולל שאלת שינוי-השם התקפה).

**תוצאה מאומתת**: התרחיש המלא (Have Book, ~12 שנה, שינוי שם בבית משפט עם מסמכים מאושרים) הפיק בהצלחה **DS-82** (לא DS-11, לא DS-5504) - תואם לכללים הרשמיים.

**באג נפרד שנתפס ותוקן - stale element ב-Step 2 (Address)**: ריצה אחת נכשלה ב-"stale element reference" בזמן מעבר בין "Preferred Method of Communication" לשדה Email - כנראה postback AJAX מלחיצת רדיו קודמת עדיין "מתיישב" כשהקוד כבר מנסה לפעול על אלמנט שנמצא. תוקן עם retry גנרי ב-`check()`/`fill_text()` שמאתר את האלמנט מחדש (`find()` טרי) אם נתפס stale, במקום לנסות שוב על אותו handle שכבר לא תקף.

**באג EC Phone (Emergency Contact Telephone) - נפתר סופית, המקור היה בשיטס לא באתר!** השדה `ecPhoneTextBox` יצא משובש ("1233645") בכמה ריצות עם "+972-50-1234567". עברתי כמה השערות שגויות (תזמון CDP, סימנים מול ספרות, אורך/קידומת מדינה) לפני שבדקתי מה `sheets_backend.load_all_applicants()` בפועל קורא מהשיטס - והתגלה **שהערך שנקרא היה `-1233645` (מספר שלם שלילי!), לא הטקסט שהוזן בכלל**. ההסבר: **Google Sheets מפרש ערך שמתחיל ב-"+" כטריגר לנוסחה** (בדיוק כמו "="), ומחשב "+972-50-1234567" כ-972-50-1234567 = **-1233645**. זה קורה גם דרך API עם `USER_ENTERED` וגם (ככל הנראה) בהקלדה ידנית רגילה בממשק - **ואפילו עיצוב התא כ-Plain Text לא מונע את זה** (נבדק ישירות: תא בפורמט TEXT עדיין מחשב את הביטוי כשהערך מוזן עם USER_ENTERED - טריגר הנוסחה של "+"/"=" חזק יותר מפורמט התא). כל "התיקונים" הקודמים (`normalize_il_phone` וכו') תיקנו את התוצאה של הבאג במקום את הסיבה, ולכן תמיד נכשלו באותה צורה.

**הפתרון בפועל**: אי אפשר למנוע את זה ב-100% ברמת השיטס, אז נוספה **בדיקת תקינות מוקדמת** (`_validate_applicant_data()` ב-`run_autofill.py`, רצה בתחילת `run_one()` לפני שנפתח דפדפן בכלל) - אם אחד השדות המספריים-כטקסט (`EC Phone`, `SSN`, `USCIS A-Number`, `Book Number`, `Mail Zip`, `Permanent Zip`, `EC Zip`) חוזר כמספר **שלילי**, זה חד-משמעית סימן שהשיטס חישב נוסחה בטעות (אף אחד מהשדות האלה לא יכול להיות שלילי באמת) - זורק שגיאה ברורה וניתנת-לפעולה ("תקן את התא, אל תתחיל עם +/-/=") **לפני** שהבוט בכלל מתחיל, במקום להריץ דפדפן שלם ולהפיק PDF עם מספר שגוי בשקט. אושר חי: מספר "0501234567" (בלי +) עבר נכון לגמרי (האתר עצמו מוריד את ה-0 המוביל ומציג "501234567" - זה תקין).

**מסקנה לעתיד**: כשמזינים מספר טלפון בינלאומי בשיטס, **אסור להתחיל ב-"+"** - להזין בלי הסימן (למשל "972501234567" או "0501234567").

## שלב 7 - Other Names - otherNameStep (זהה לכולם, מופיע בכל מקרה בהמשך התהליך)

"List all other names you have used" - טבלה עם Other First Name + Other Last Name, וכפתור "Add Another Name" להוספת שורות נוספות (כמה כינויים/שמות קודמים שצריך).

## שלב 8 - Personal Application Review - reviewStep

עמוד סיכום/בדיקה לפני הדפסה ("Check your information before printing your form") - מציג את כל מה שהוזן. ללא שדות קלט חדשים למיפוי (לבדוק בהמשך אם יש checkbox אישור).

## שלב 9 - Passport Products and Fees - feesStep

בחירת מוצר (רדיו, חובה): Passport Book ($130) / Passport Card ($30) / Passport Book & Card ($160).
**כלל עסקי**: תמיד בוחרים **Passport Book** בלבד.

כשבוחרים Book, נפתחות עוד 3 קבוצות בחירה:
- **Large Book (Non-Standard)** - checkbox. **כלל עסקי: לעולם לא מסמנים** (נשאר לא מסומן).
- **Processing Methods** (רדיו, חובה): Routine Service ($0, ברירת מחדל) / Expedited Service ($60) / Expedited at Agency Service ($60). **כלל עסקי: תמיד Routine Service, לעולם לא שירות מהיר.**
- **Delivery Methods** (רדיו, ל-Book): Standard Delivery ($0, ברירת מחדל) / 1-3 Day Delivery ($23.36). לא צוין כלל מפורש - כנראה גם כאן נשארים על ברירת המחדל (Standard).

**הערה חשובה**: המחיר המוצג ($130 וכו') משתנה אוטומטית לפי גיל המבקש (קטין מול בגיר) ולפי נתוני הדרכון הקודם (למשל אם הונפק לפני יותר מ-15 שנה) - **זה מחושב אוטומטית ע"י המערכת מתוך נתונים שכבר הוזנו (תאריך לידה, תאריך הנפקה קודם), ולא דורש שדה נוסף בשיטס**. רק לשים לב בבדיקת התוצאה הסופית שהמחיר תואם את המצב בפועל.

**אישור**: כשהדרכון הקודם הונפק לפני 15 שנה ומעלה, האתר עובר בפועל למסלול **DS-11** (במקום DS-82) ומוסיף שלב נוסף - ראה שלב 10 למטה.

## שלב 10 - Applicant's Parent & Spouse Information - moreAboutYouStep (ייחודי למסלול DS-11!)

זהו שלב נוסף שנפתח **רק** כשעוברים למסלול DS-11 (למשל בגלל דרכון קודם בן 15+ שנה, מידע שגוי, או שינוי שם לא מוכח - כמו שנרשם בשלב 6).

**סדר השלבים במסלול DS-11 שונה מ-DS-82**: שלב זה (Parent & Spouse Info) מופיע **לפני** שלב "Other Names" (שסומן קודם כ-7). כלומר הסדר במסלול DS-11 הוא: ...שלב 6 (Most Recent Passport Continued) → **שלב 10 (Parent & Spouse Info)** → שלב 7 (Other Names) → ...

**הורה 1 (Mother/Father/Parent):**
- checkbox "Unknown" (אם ההורה לא ידוע) - **צריך אימות** אם זה מסתיר את שאר השדות של ההורה הזה כשמסומן.
- First & Middle Name (at Parent's Birth) - שדה משולב אחד (לא שני שדות נפרדים)
- Last Name (at Parent's Birth)
- Date Of Birth (MM/DD/YYYY)
- Place Of Birth
- Sex (M/F)
- U.S. Citizen (Yes/No)

**הורה 2:** אותו מבנה בדיוק (checkbox Unknown + First&Middle Name + Last Name + DOB + Place of Birth + Sex + US Citizen).

**מצב משפחתי:**
- "Has Applicant Ever Been Married?" (Yes/No, חובה)
  - אם **Yes** נפתח: First & Middle Name של בן/בת הזוג, Last Name, Date Of Birth, Place Of Birth, U.S. Citizen (Yes/No), Date Of Most Recent Marriage.
    - ובתוך זה נפתחת גם: "Has applicant ever been widowed or divorced?" (Yes/No) - אם **Yes**: Divorce Date (MM/DD/YYYY).

**חסר לאימות**: מה קורה כשמסמנים Unknown אצל הורה, וכשעונים No על "Ever Been Married" (כנראה שום דבר נוסף לא נדרש, בדומה לתבנית שחזרה על עצמה בשלבים קודמים).

### הבדל ב-Fees בין DS-11 ל-DS-82

במסלול DS-11 מופיעה בעמוד ה-Fees (שלב 9) קבוצה נוספת **"Additional Fees"** עם **Execution (Acceptance) Fee: $35** - זה checkbox קבוע (מסומן, disabled - לא ניתן לשינוי, חל תמיד באופן אוטומטי ב-DS-11 כי צריך להופיע פיזית מול פקיד).

פירוט התשלום ל-DS-11 (Book, Routine, Standard Delivery): 
- Payable to Department of State: $130.00
- Payable to your acceptance facility: $35.00
- **Total: $165.00**

לעומת DS-82 (חידוש בדואר, בלי הופעה אישית) שם אין Execution Fee בכלל וה-Total היה $130.00 בלבד. **זה לא שדה שממלאים - זה מוצג אוטומטית לפי סוג הטופס (DS-11/DS-82) שנקבע משאלות קודמות.**

### תיקון חשוב (2026-08-09): יש טופס שלישי - DS-5504, לא רק DS-11/DS-82

**"שלב 10 (Parent & Spouse) לא הופיע" ≠ "זה DS-82"!** בדקנו בפועל PDF שיצא מתרחיש **Limited Validity = Yes** (לא הגיע לשלב ההורים) - הכותרת בפועל הייתה **`DS-5504`**: *"CORRECTION, NAME CHANGE TO PASSPORT ISSUED 1 YEAR AGO OR LESS, AND LIMITED PASSPORT REPLACEMENT"*. כלומר טופס DS-5504 אחד מכסה **שלושה** מקרי-שימוש שונים: (א) תיקון נתונים, (ב) שינוי שם לדרכון שהונפק לפני שנה או פחות, (ג) החלפת דרכון מוגבל-תוקף - התרחיש שלנו (Limited Validity) נופל בקטגוריה (ג).

**מבחינת הבוט/הגיליון זה לא משנה** - גם DS-82 וגם DS-5504 לא דורשים את קטע ההורים, אז אין צורך להבחין ביניהם בקוד. אבל **בהודעות הלוג ובתיעוד לא להניח "DS-82"** כשמה שבאמת ידוע זה רק "לא DS-11".

**עדיין לא נבדק/לא ברור**: ההבחנה בין "פחות משנה" ל"יותר משנה" (לפי הלקוח, ייתכן שמשפיעה על קטגוריה ב' - שינוי שם - לא בהכרח על קטגוריה ג' שבדקנו) - צריך לבדוק בעתיד אם ורלוונטי.

**תיקון נוסף לתנאי השדרוג ל-DS-11**: מ-2 בדיקות היום (E: חידוש-ילד לא-מוגבל שכן עלה ל-DS-11, מול F: חידוש-מבוגר מוגבל שנשאר DS-5504) - נראה שהגורם האמיתי הוא **גיל ההנפקה של הדרכון הקודם מתחת ל-16**, **לא** "Limited Validity=Yes" כמו שחשבנו קודם. כלומר תנאי השדרוג המלא: Scenario=First-time, **או** גיל בזמן הנפקת הדרכון הקודם < 16, **או** דרכון קודם בן 15+ שנה, **או** Data Printed Correctly=No, **או** Name Changed=Yes, **או** (Lost/Stolen וגם לא-דווח).

## שלב 14 - Valid Lost Or Stolen U.S. Passport Information - lostStolenStep

**התגלה בהרצה חיה ב-2026-08-05, לא היה ידוע קודם.** קובץ שמור: `14.html`.

**מתי מופיע**: רק כש-Passport Scenario = Book Lost / Book Stolen **וגם** "Reported Lost or Stolen?" = **No** (כלומר עוד לא דיווחו על האובדן/גניבה). מופיע **מייד אחרי שלב 8 (Review), לפני שלב 9 (Fees)** - **תיקון (2026-08-05)**: בהתחלה חשבנו שזה אחרי Fees, כי לוג ההרצה הראה "Step 9: Fees" ואז נכשל - אבל זה היה מטעה: שלב Fees רק *נכנס* ומדפיס את הכותרת שלו, ובפועל כבר היינו על עמוד ה-Lost/Stolen (ה-timeout היה כי Fees ניסה למלא שדות שלא קיימים בעמוד הזה). כלומר Fees נשאר תמיד השלב האחרון בפועל (כפתור Finish כרגיל) - רק שיש לו שלב Lost/Stolen לפניו לפעמים.

**שדות (כולם חובה):**
1. **"Are you reporting your own valid lost or stolen U.S. passport?"** (Yes/No) - `lostStolenStep_reporterYesRadioButton` / `reporterNoRadioButton`. אם No - לא ניתן להגיש דיווח אונליין, רק להדפיס טופס DS-64 לחתימה ושליחה בדואר.
2. **"Did you file a police report?"** (Yes/No) - `lostStolenStep_policeReportYesRadioButton1` / `policeReportNoRadioButton1`.
3. **"Explain in detail how your valid U.S. passport book was lost or stolen"** (טקסט חופשי, מוגבל ל-115 תווים ע"י JS) - `lostStolenStep_bookLostHowTextBox`.
4. **"Explain where the loss or theft occurred"** (טקסט חופשי, 115 תווים) - `lostStolenStep_bookLostWhereTextBox`.
5. **"On what date was your valid U.S. passport book lost or stolen?"** (MM/DD/YYYY) - `lostStolenStep_bookLostDateTextBox`.
6. **"Have you had any other valid U.S. passport book/card lost or stolen?"** (Yes/No) - `lostStolenStep_lostPrevYesRadioButton` / `lostPrevNoRadioButton`.

לוחצים Next רגיל (`StepNavigationTemplateContainerID_StartNextPreviousButton`) בסיום - זה מוביל לשלב האחרון (Next Steps).

**עמודות בשיטס**: נוספה קבוצה "LOST OR STOLEN REPORT" עם Reporting Own Passport? / Filed Police Report? / Lost/Stolen Explanation / Lost/Stolen Location / Lost/Stolen Date / Other Passports Lost/Stolen?.

**חשוב - "אפקט דומינו" על שלבים קודמים**: מילוי השלב הזה יכול לגרום לאתר להחליט (בדיעבד) ששדרוג DS-11 כן נדרש, גם אם קודם (אחרי שלב 6) הוא נראה כמסלול DS-82 נקי. במקרה כזה, האתר **חוזר** ומציג שוב, בסדר הזה: Parent & Spouse Info (שלב 10) → Other Names (שלב 7) → Review (שלב 8) - לפני שממשיכים ל-Fees. הקוד מטפל בזה ע"י קריאה שנייה (אדפטיבית, לא מזיקה אם לא באמת מופיע) לשלושת השלבים האלה אחרי שלב ה-Lost/Stolen.

## שלב 15 - Electronic Signature (DS-64) - esignatureStep

**מופיע אחרי שלב 9 (Fees), רק במסלול Lost/Stolen.** שאלה: "How would you like to send your statement regarding a Valid Lost or Stolen U.S. Passport?" - Sign and Send Online / **Print, Sign and Mail**.

**כלל עסקי (אושר עם הלקוח ב-2026-08-05)**: תמיד **Print, Sign and Mail** - `esignatureStep_lostOrStolenDelivery_1`. העסק לעולם לא שולח אונליין, תמיד מדפיס לחתימה ושליחה עצמאית של הלקוח.

## שלב אחרון - Next Steps - nextStepsStep (זהה לכולם, סוף התהליך)

עמוד סיכום סופי. **אין שדות מידע נוספים למלא**. הפעולה היחידה הנדרשת:
1. לסמן checkbox: **"I have read and acknowledged the steps and information contained above."** (חובה)
2. ללחוץ על כפתור **"Print Form"** - זה מה שמוריד/מייצר את קובץ ה-PDF הסופי.

כל שאר האופציות בעמוד הזה (Submit Online וכו') **לא רלוונטיות** לתהליך שלנו - אנחנו תמיד רק מורידים PDF להדפסה וחתימה ידנית.

---

## קצב הרצה (סוכם עם הלקוח)

דפדפן headed בלבד, לעולם לא הרצה מקבילה (רק בזה אחר זה), והשהיות רציניות לאורך כל התהליך: כ-1.5-3.5 שניות בין מילוי כל שדה, וכ-7-15 שניות בין כל מעבר שלב (כפתור Next). מומלץ גם להגביל נפח יומי/לפזר על פני שעות, ולעצור מיד אם מופיע אתגר/CAPTCHA לא צפוי במקום לנסות שוב. מומש ב-`run_autofill.py`.

## נשאר למפות (מסלולים נוספים)

1. ~~**דרכון ראשון (First-time applicant) - מבוגר**~~ - **מאושר**: אותם עמודים בדיוק שכבר מופו (Parent & Spouse Info → Other Names → Fees). עלות $165.
2. ~~**דרכון ראשון - ילד (קטין)**~~ - **מאושר**: אותם עמודים בדיוק. עלות $135 (הפרש אוטומטי, כנראה עמלת ספר קטין $100+$35 execution).
3. ~~**חידוש דרכון - ילד (קטין)**~~ - **מאושר**: אותם עמודים בדיוק. עלות $135.
4. ~~**חידוש למבוגר שהדרכון הקודם שלו הונפק כשהיה ילד**~~ - **מאושר**: גם זה מבקש Parent Info כמו DS-11 רגיל, ועלות $165 (מחיר מבוגר, כי המבקש כרגע הוא מבוגר גם אם הדרכון הישן הונפק בילדותו) - לא $135.
5. ~~**דרכון שמחליף דרכון זמני/מוגבל-תוקף**~~ - **מאושר**: ראה פירוט למטה.

### מסלול 5 - דרכון שמחליף דרכון זמני/מוגבל-תוקף (תוספת לשלב 6 - mostRecentPassportContinued)

כשהמערכת מזהה שהדרכון הקודם הונפק **בשנתיים האחרונות**, מופיעה שאלה נוספת בשלב 6 (לפני/בנוסף לשאלות "הודפס נכון"/"השם השתנה"):

- **"Was your most recent passport book limited for two years or less?"** (Yes/No, חובה)
  - אם **Yes**: נפתחת עוד שאלה - **"Did you pay for a card the last time you applied?"** (Yes/No, חובה)

**תוצאה**: כשמדובר בהחלפת דרכון זמני/מוגבל-תוקף כזה, העלות הסופית בעמוד ה-Fees היא **$0**.

**הערה חשובה מהלקוח**: העלות המוצגת ($130/$135/$165 וכו') **לא רלוונטית בפועל** - אנחנו לא משלמים באתר, רק מורידים PDF. המחיר משמש רק כ**בדיקת שפיות (sanity check)** - אם המחיר לא תואם את הציפייה, זה סימן שאולי תאריך לידה או תאריך הנפקה הוזנו לא נכון.

### אופציה 4 - First-time applicant
בעמוד 4 עצמו לא נפתח שום שדה נוסף (זה נכון). **אבל** - מכיוון שאין דרכון קודם, זה תמיד DS-11, כלומר שלב 10 (Parent & Spouse Info) **תמיד** מופיע בהמשך התהליך גם למבקש פעם-ראשונה (בדיוק כמו בטבלת "מסלולים מאושרים" למעלה: פריטים 1,2 - דרכון ראשון מבוגר/ילד - שניהם קיבלו את עמוד ההורים). שלב 6 (הודפס נכון/השם השתנה) הוא היחיד שבאמת לא רלוונטי/לא אמור להופיע כשאין דרכון קודם להשוות אליו.
