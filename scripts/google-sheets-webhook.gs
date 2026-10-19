// Google 스프레드시트에서 [확장 프로그램] > [Apps Script] 메뉴로 열어서
// 아래 코드를 전부 붙여넣고 웹 앱으로 배포하세요. (사용법은 배포 가이드 참고)

var SHARED_TOKEN = "여기에_원하는_비밀토큰_입력"; // .env의 GOOGLE_SHEETS_WEBHOOK_TOKEN과 동일하게 설정 (이 파일은 git에 커밋되므로 실제 값을 직접 적지 마세요)

// [payload 키, 시트 컬럼 헤더] 쌍의 목록. 순서가 곧 시트의 컬럼 순서이며,
// 헤더 행과 데이터 행 모두 이 배열 하나로부터 만들어지므로 둘이 어긋날 수 없다.
// 새 필드를 추가할 때는 이 배열에 한 줄만 추가하면 된다.
var FIELDS = [
  ["timestamp", "시각"],
  ["student_id", "학번"],
  ["student_name", "학생 이름"],
  ["case_label", "윤리 갈등 사례"],
  ["selected_principle", "선택한 윤리 원칙"],
  ["turn_count", "발화 횟수"],
  ["choice_talk_score", "Choice Talk 점수"],
  ["choice_talk_comment", "Choice Talk 피드백"],
  ["option_talk_score", "Option Talk 점수"],
  ["option_talk_comment", "Option Talk 피드백"],
  ["decision_talk_score", "Decision Talk 점수"],
  ["decision_talk_comment", "Decision Talk 피드백"],
  ["ethical_reasoning_score", "Ethical Reasoning 점수"],
  ["ethical_reasoning_comment", "Ethical Reasoning 피드백"],
  ["step3_reflection", "학생 성찰 내용 (9단계)"],
  ["overall_comment", "총평"],
  ["transcript", "대화 전문"],
  // 기존 시트의 컬럼이 밀리지 않도록 새 필드는 맨 뒤에 추가한다.
  ["total_score", "총점 (40점 만점)"],
];

function doPost(e) {
  var data = JSON.parse(e.postData.contents);

  if (data.token !== SHARED_TOKEN) {
    return ContentService.createTextOutput(JSON.stringify({ error: "invalid token" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  // 여러 학생이 동시에 [피드백 받기]를 눌러도 헤더 중복 생성이나 행 유실 없이
  // 한 번에 한 요청만 시트에 쓰도록 직렬화한다. 락을 못 잡으면(다른 요청이
  // 오래 걸리는 중) 즉시 에러를 반환해 클라이언트가 재시도하도록 한다.
  var lock = LockService.getScriptLock();
  var gotLock = lock.tryLock(15000);
  if (!gotLock) {
    return ContentService.createTextOutput(JSON.stringify({ error: "server busy, please retry" }))
      .setMimeType(ContentService.MimeType.JSON);
  }

  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("기록") ||
      SpreadsheetApp.getActiveSpreadsheet().insertSheet("기록");

    if (sheet.getLastRow() === 0) {
      sheet.appendRow(FIELDS.map(function (f) { return f[1]; }));
    } else if (sheet.getLastColumn() < FIELDS.length) {
      // 필드가 추가되기 전에 만들어진 시트라면 빠진 헤더만 채워 넣는다.
      var start = sheet.getLastColumn();
      sheet.getRange(1, start + 1, 1, FIELDS.length - start)
        .setValues([FIELDS.slice(start).map(function (f) { return f[1]; })]);
    }

    sheet.appendRow(FIELDS.map(function (f) {
      var value = data[f[0]];
      return value === undefined || value === null ? "" : value;
    }));
  } finally {
    lock.releaseLock();
  }

  return ContentService.createTextOutput(JSON.stringify({ ok: true }))
    .setMimeType(ContentService.MimeType.JSON);
}
