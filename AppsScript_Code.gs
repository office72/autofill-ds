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
