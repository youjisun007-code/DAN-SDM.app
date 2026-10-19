(function () {
  const chatWindow = document.getElementById("chat-window");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const chatSendBtn = document.getElementById("chat-send-btn");
  const endBtn = document.getElementById("end-visit-btn");
  const feedbackArea = document.getElementById("feedback-area");
  const feedbackPlaceholder = document.getElementById("feedback-placeholder");
  const feedbackList = document.getElementById("feedback-list");
  const totalScoreBadge = document.getElementById("total-score-badge");
  const turnCountEl = feedbackArea.querySelector(".turn-count");
  const overallCommentEl = feedbackArea.querySelector(".overall-comment");
  const optionsDebrief = document.getElementById("options-debrief");
  const optionsList = document.getElementById("options-list");
  const studentIdInput = document.getElementById("student-id");
  const studentNameInput = document.getElementById("student-name");
  const principleSelect = document.getElementById("principle-select");
  const principleCards = document.querySelectorAll(".principle-card");

  const step1Panel = document.getElementById("step1-panel");
  const step2Panel = document.getElementById("step2-panel");
  const step3Panel = document.getElementById("step3-panel");
  const startSdmBtn = document.getElementById("start-sdm-btn");
  const submitFeedbackBtn = document.getElementById("submit-feedback-btn");
  const step3Reflection = document.getElementById("step3-reflection");
  const step1ErrorEl = document.getElementById("step1-error");
  const step3ErrorEl = document.getElementById("step3-error");
  const turnCounterLive = document.getElementById("turn-counter");
  const step3Intro = document.getElementById("step3-intro");

  const mobileBackToChatBtn = document.getElementById("mobile-back-to-chat-btn");
  const mobileToReportBtn = document.getElementById("mobile-to-report-btn");

  const TOTAL_TURNS = window.SDM_TOTAL_TURNS || 9;
  const EARLY_END_TURN = window.SDM_EARLY_END_TURN || 6;

  const history = [];
  let conversationEnded = false;
  let selectedPrincipleId = null;
  let studentTurnCount = 0;

  principleCards.forEach(function (card) {
    card.addEventListener("click", function () {
      principleCards.forEach(function (c) {
        c.classList.remove("selected");
      });
      card.classList.add("selected");
      selectedPrincipleId = card.dataset.principleId;
      principleSelect.classList.remove("invalid");
    });
  });

  try {
    const savedId = localStorage.getItem("student-id");
    if (savedId) studentIdInput.value = savedId;
    const savedName = localStorage.getItem("student-name");
    if (savedName) studentNameInput.value = savedName;
  } catch (err) {
    /* localStorage 사용 불가 시 무시 */
  }

  function getStudentInfo() {
    const id = studentIdInput.value.trim();
    const name = studentNameInput.value.trim();

    if (!id) {
      studentIdInput.classList.add("invalid");
      studentIdInput.focus();
      return null;
    }
    studentIdInput.classList.remove("invalid");

    if (!name) {
      studentNameInput.classList.add("invalid");
      studentNameInput.focus();
      return null;
    }
    studentNameInput.classList.remove("invalid");

    if (!selectedPrincipleId) {
      principleSelect.classList.add("invalid");
      principleSelect.scrollIntoView({ behavior: "smooth", block: "center" });
      return null;
    }
    principleSelect.classList.remove("invalid");

    try {
      localStorage.setItem("student-id", id);
      localStorage.setItem("student-name", name);
    } catch (err) {
      /* localStorage 사용 불가 시 무시 */
    }
    return { id: id, name: name, principle: selectedPrincipleId };
  }

  function markField(el, valid) {
    el.classList.toggle("invalid", !valid);
  }

  // 모바일(768px 이하)에서는 body[data-mobile-step] 값에 따라 CSS가 한 화면만 보여준다.
  // 데스크톱에서는 이 값이 레이아웃에 영향을 주지 않는다.
  const mobileQuery = window.matchMedia("(max-width: 768px)");

  function setMobileStep(step) {
    document.body.dataset.mobileStep = String(step);
    if (mobileQuery.matches) window.scrollTo(0, 0);
  }

  mobileBackToChatBtn.addEventListener("click", function () {
    setMobileStep(2);
  });

  mobileToReportBtn.addEventListener("click", function () {
    setMobileStep(3);
  });

  function setLoading(button, isLoading, loadingText, normalText) {
    button.disabled = isLoading;
    button.textContent = isLoading ? loadingText : normalText;
  }

  // --- Google Sheets 전송 실패 시 로컬 백업 + 재전송 (다인원 동시 접속 대비) ---
  var PENDING_SYNC_KEY = "dna-sdm-pending-sync";

  function loadPendingSync() {
    try {
      var raw = localStorage.getItem(PENDING_SYNC_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (err) {
      return [];
    }
  }

  function savePendingSync(list) {
    try {
      localStorage.setItem(PENDING_SYNC_KEY, JSON.stringify(list));
    } catch (err) {
      /* localStorage 사용 불가 시 무시 (재전송 큐는 best-effort) */
    }
  }

  function addPendingSync(payload) {
    var list = loadPendingSync();
    list.push(payload);
    savePendingSync(list);
  }

  async function trySync(payload) {
    try {
      const res = await fetch("/api/resync-sheet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      return !!data.logged_to_sheet;
    } catch (err) {
      return false;
    }
  }

  async function flushPendingSync() {
    var list = loadPendingSync();
    if (list.length === 0) return;
    var remaining = [];
    for (var i = 0; i < list.length; i++) {
      var ok = await trySync(list[i]);
      if (!ok) remaining.push(list[i]);
    }
    savePendingSync(remaining);
    if (remaining.length < list.length) {
      console.log(
        "대기 중이던 시트 기록 " + (list.length - remaining.length) + "건 재전송 완료, " +
        remaining.length + "건 남음"
      );
    }
  }

  function showError(el, message) {
    el.textContent = message;
    el.hidden = false;
  }

  function clearError(el) {
    el.hidden = true;
  }

  function addBubble(role, text) {
    const bubble = document.createElement("div");
    bubble.className = "bubble " + role;

    const tag = document.createElement("span");
    tag.className = "role-tag";
    tag.textContent = role === "student" ? "나(한의사)" : "상대방";

    const body = document.createElement("span");
    body.textContent = text;

    bubble.appendChild(tag);
    bubble.appendChild(body);
    chatWindow.appendChild(bubble);
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  function scoreClass(score) {
    if (score >= 8) return "ok";
    if (score >= 5) return "warn";
    return "bad";
  }

  function finishConversation(introMessage) {
    if (conversationEnded) return;
    conversationEnded = true;
    chatInput.disabled = true;
    chatSendBtn.disabled = true;
    endBtn.disabled = true;

    step2Panel.hidden = true;
    step3Panel.hidden = false;
    if (introMessage) {
      step3Intro.textContent = introMessage;
      step3Intro.hidden = false;
    } else {
      step3Intro.hidden = true;
    }
    step3Panel.scrollIntoView({ behavior: "smooth", block: "start" });
    step3Reflection.focus();
  }

  startSdmBtn.addEventListener("click", function () {
    clearError(step1ErrorEl);

    if (!getStudentInfo()) {
      if (studentIdInput.classList.contains("invalid")) {
        showError(step1ErrorEl, "학번을 입력해주세요.");
      } else if (studentNameInput.classList.contains("invalid")) {
        showError(step1ErrorEl, "이름을 입력해주세요.");
      } else if (principleSelect.classList.contains("invalid")) {
        showError(step1ErrorEl, "위에서 윤리 원칙 카드를 하나 선택해주세요.");
      }
      return;
    }

    step1Panel.hidden = true;
    step2Panel.hidden = false;
    setMobileStep(2);
    step2Panel.scrollIntoView({ behavior: "smooth", block: "start" });
    chatInput.focus({ preventScroll: true });
  });

  chatForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    if (conversationEnded) return;
    if (!getStudentInfo()) return;

    const message = chatInput.value.trim();
    if (!message) return;

    addBubble("student", message);
    history.push({ role: "student", text: message });
    chatInput.value = "";
    chatInput.disabled = true;
    setLoading(chatSendBtn, true, "전송 중...", "전송");

    let turnCompleted = false;

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: message,
          history: history.slice(0, -1), // 방금 추가한 학생 발화 제외 (message로 별도 전달)
        }),
      });
      const data = await res.json();
      addBubble("counterpart", data.reply);
      history.push({ role: "counterpart", text: data.reply });
      turnCompleted = true;
    } catch (err) {
      addBubble("counterpart", "(오류: 응답을 받아오지 못했습니다)");
    } finally {
      chatInput.disabled = false;
      setLoading(chatSendBtn, false, "전송 중...", "전송");
      chatInput.focus({ preventScroll: true });
    }

    if (!turnCompleted) return;

    studentTurnCount += 1;
    turnCounterLive.textContent = "대화 진행: " + studentTurnCount + " / " + TOTAL_TURNS + "턴";

    if (studentTurnCount >= EARLY_END_TURN) {
      endBtn.disabled = false;
    }

    if (studentTurnCount >= TOTAL_TURNS) {
      finishConversation(
        "모든 상담 단계(" + TOTAL_TURNS + "턴)가 완료되었습니다. 아래에서 Step 3 사후 성찰을 작성해 주세요."
      );
    }
  });

  endBtn.addEventListener("click", function () {
    finishConversation();
  });

  submitFeedbackBtn.addEventListener("click", async function () {
    clearError(step3ErrorEl);
    const reflection = step3Reflection.value.trim();
    markField(step3Reflection, reflection.length > 0);
    if (!reflection) {
      step3Reflection.focus();
      showError(step3ErrorEl, "성찰문을 작성해주세요.");
      return;
    }

    setLoading(submitFeedbackBtn, true, "채점 중...", "피드백 받기");

    const studentIdValue = studentIdInput.value.trim();
    const studentNameValue = studentNameInput.value.trim();

    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          history: history,
          student_id: studentIdValue,
          student_name: studentNameValue,
          selected_principle: selectedPrincipleId,
          step3_reflection: reflection,
        }),
      });
      const data = await res.json();
      console.log("시트 저장 완료 여부:", data.logged_to_sheet, data);

      if (data.categories && data.categories.length > 0 && !data.logged_to_sheet) {
        // 시트 전송에 실패했어도 채점 결과는 이미 받았으므로, Claude를 다시 부르지
        // 않고도 재전송할 수 있도록 로컬에 백업해두고 한 번 더 시도해본다.
        const backupPayload = {
          student_id: studentIdValue,
          student_name: studentNameValue,
          case_label: data.case_label || "",
          history: history,
          categories: data.categories,
          overall_comment: data.overall_comment,
          selected_principle_label: data.selected_principle_label || "",
          step3_reflection: reflection,
        };
        addPendingSync(backupPayload);
        trySync(backupPayload).then(function (ok) {
          if (ok) {
            var remaining = loadPendingSync().filter(function (p) {
              return JSON.stringify(p) !== JSON.stringify(backupPayload);
            });
            savePendingSync(remaining);
            console.log("백업해뒀던 시트 기록 재전송 성공");
          }
        });
      }

      turnCountEl.textContent = "학생 발화 횟수: " + data.turn_count + "회";

      if (typeof data.total_score === "number" && data.categories && data.categories.length > 0) {
        totalScoreBadge.querySelector("strong").textContent = data.total_score;
        totalScoreBadge.hidden = false;
      } else {
        totalScoreBadge.hidden = true;
      }

      feedbackList.innerHTML = "";
      (data.categories || []).forEach(function (cat) {
        const li = document.createElement("li");
        li.className = "feedback-item";

        const titleRow = document.createElement("div");
        titleRow.className = "item-title";

        const titleSpan = document.createElement("span");
        titleSpan.textContent = cat.title;

        const scoreSpan = document.createElement("span");
        scoreSpan.className = "score " + scoreClass(cat.score);
        scoreSpan.textContent = cat.score + "/10";

        titleRow.appendChild(titleSpan);
        titleRow.appendChild(scoreSpan);

        const commentDiv = document.createElement("div");
        commentDiv.className = "comment";
        commentDiv.textContent = cat.comment;

        li.appendChild(titleRow);
        li.appendChild(commentDiv);
        feedbackList.appendChild(li);
      });

      overallCommentEl.textContent = data.overall_comment;
      feedbackPlaceholder.hidden = true;
      feedbackArea.hidden = false;

      optionsList.innerHTML = "";
      const opts = data.options || [];
      if (opts.length > 0) {
        opts.forEach(function (opt) {
          const li = document.createElement("li");
          const idSpan = document.createElement("span");
          idSpan.className = "opt-id";
          idSpan.textContent = opt.id + "안.";
          li.appendChild(idSpan);
          li.appendChild(document.createTextNode(opt.desc));
          optionsList.appendChild(li);
        });
        optionsDebrief.hidden = false;
      } else {
        optionsDebrief.hidden = true;
      }
    } catch (err) {
      feedbackPlaceholder.hidden = true;
      overallCommentEl.textContent = "피드백을 불러오지 못했습니다.";
      feedbackArea.hidden = false;
    } finally {
      setLoading(submitFeedbackBtn, false, "채점 중...", "피드백 받기");
      mobileToReportBtn.hidden = false;
      setMobileStep(3);
    }
  });

  // 접속 중간에 끊겨서 시트 전송을 못 했던 이전 세션의 백업이 있으면 조용히 재전송을 시도한다.
  flushPendingSync();

  // 초기 인사 메시지 (고정 대사, Claude 호출 없이 표시)
  addBubble("counterpart", window.CASE_OPENING_LINE || "안녕하세요, 선생님.");
})();
