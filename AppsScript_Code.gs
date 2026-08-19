function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('AUTOFILL')
    .addItem('▶ הרץ', 'runAutofill')
    .addToUi();
}

function runAutofill() {
  var sheetId = SpreadsheetApp.getActiveSpreadsheet().getId();
  var url = 'passportbot://run?sheet=' + sheetId;
  var html = HtmlService.createHtmlOutput(
    '<html><body style="font-family:sans-serif;padding:16px;">' +
    '<p>אם ההרצה לא נפתחה אוטומטית, ' +
    '<a href="' + url + '" target="_blank">לחצו כאן</a>.</p>' +
    '<script>window.open("' + url + '", "_blank");' +
    'setTimeout(function(){ google.script.host.close(); }, 800);</script>' +
    '</body></html>'
  ).setWidth(350).setHeight(120);
  SpreadsheetApp.getUi().showModalDialog(html, 'מריץ את הבוט...');
}

// ---- "לקוח חדש" - Web App שזוהו קורא לו כדי לשכפל את התבנית לתיקיית לקוח ----
//
// למה זה עובד בלי בעיית-הרשאות: Web App הזה מפורסם עם "Execute as: Me" - כך
// שכל קריאה חיצונית (מזוהו) מריצה את makeCopy() בתור בן-האדם שפרסם את
// ה-deployment, לא בתור service account - בדיוק כמו לחיצה ידנית על "▶ הרץ".
// זה מה שמאפשר להעתק שנוצר לרוץ מייד, בלי אישור נוסף ובלי געת ב-Admin Console.
//
// הסוד חייב להישאר תואם לזה שמוטבע בקוד ה-Deluge בזוהו (כמו TRIGGER_SECRET
// הקיים לכפתור המקביל של document-analyzer - אותו עיקרון: השירות פתוח-לכולם
// כי Deluge לא יכול לחתום טוקן גוגל, ולכן ההגנה היא סוד-משותף בגוף הבקשה).
var NEW_CLIENT_SECRET = 'KML6bPxugQABX4NPzDLzlwbA_hdIeDVY';

function doPost(e) {
  return _handleNewClientRequest(e);
}

function doGet(e) {
  return _handleNewClientRequest(e);
}

function _handleNewClientRequest(e) {
  var params = (e && e.parameter) || {};

  if (params.secret !== NEW_CLIENT_SECRET) {
    return _jsonOutput({status: 'error', message: 'סוד לא תקין'});
  }

  var folderId = params.folder_id;
  var clientName = params.client_name || 'לקוח חדש';
  if (!folderId) {
    return _jsonOutput({status: 'error', message: 'חסר folder_id'});
  }

  try {
    var templateFile = DriveApp.getFileById(SpreadsheetApp.getActiveSpreadsheet().getId());
    var targetFolder = DriveApp.getFolderById(folderId);
    var copy = templateFile.makeCopy('AUTOFILL - ' + clientName, targetFolder);
    return _jsonOutput({
      status: 'ok',
      file_id: copy.getId(),
      url: 'https://docs.google.com/spreadsheets/d/' + copy.getId() + '/edit',
    });
  } catch (err) {
    return _jsonOutput({status: 'error', message: String(err)});
  }
}

function _jsonOutput(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
