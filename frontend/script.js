const typingForm = document.querySelector(".typing-form");
const chatList = document.querySelector(".chat-list");
const suggestions = document.querySelectorAll(".suggestion-list .suggestion");
const toggleThemeButton = document.querySelector("#toggle-theme-button");
const deleteChatButton = document.querySelector("#delete-chat-button");
const toggleInterfaceBtn = document.getElementById("toggle-interface-btn");
const bookDropdown = document.getElementById("book-dropdown");

let userMessage = null;
let isResponseGenerating = false;
let currentQuestionId = null; // For study mode
let currentTestQuestionId = null; // For test mode

// Global variable to indicate current interface mode: "study" or "test"
let interfaceMode = localStorage.getItem("interfaceMode") || "study";

// Load theme (saved chat functionality removed)
const loadTheme = () => {
  const isLightMode = localStorage.getItem("themeColor") === "light_mode";
  document.body.classList.toggle("light_mode", isLightMode);
  toggleThemeButton.innerText = isLightMode ? "dark_mode" : "light_mode";
};

loadTheme();

// --- Dynamic document selection ---

// Toggle dropdown display when "Choose Book" is clicked
function toggleBookDropdown() {
  if (bookDropdown.style.display === "none" || bookDropdown.style.display === "") {
    loadDocumentList();
    bookDropdown.style.display = "block";
  } else {
    bookDropdown.style.display = "none";
  }
}

// Fetch the current user's uploaded documents and render them in the dropdown.
async function loadDocumentList() {
  try {
    const res = await fetch("/api/documents");
    if (!res.ok) return;
    const documents = await res.json();
    bookDropdown.innerHTML = "";

    if (!documents.length) {
      bookDropdown.innerHTML = '<div class="dropdown-item" style="padding: 8px; color: #888;">No documents yet</div>';
      return;
    }

    documents.forEach((doc) => {
      const item = document.createElement("div");
      item.className = "dropdown-item";
      item.style.padding = "8px";
      item.style.cursor = doc.status === "ready" ? "pointer" : "default";
      item.style.color = doc.status === "ready" ? "" : "#888";

      let label = doc.filename;
      if (doc.status === "processing") label += " (processing…)";
      if (doc.status === "failed") label += " (failed)";
      item.innerText = label;

      if (doc.status === "ready") {
        item.addEventListener("click", () => selectDocument(doc.id, doc.filename));
      }
      bookDropdown.appendChild(item);
    });
  } catch (error) {
    console.error("Error loading document list:", error);
  }
}

// Called when a ready document is clicked in the dropdown.
async function selectDocument(documentId, filename) {
  try {
    bookDropdown.style.display = "none";
    const formData = new FormData();
    formData.append("document_id", documentId);
    const res = await fetch("/api/select_document", {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Error selecting document");
    console.log("Document selection:", data);
    alert(data.msg);
    window.location.reload();
  } catch (error) {
    console.error("Error selecting document:", error);
    alert(error.message);
  }
}

// Poll a processing document's status until it's ready or failed.
async function pollDocumentStatus(documentId) {
  const statusEl = document.getElementById("upload-status");
  const poll = async () => {
    try {
      const res = await fetch(`/api/documents/${documentId}/status`);
      const data = await res.json();
      if (data.status === "processing") {
        statusEl.innerText = "Processing document…";
        setTimeout(poll, 3000);
      } else if (data.status === "ready") {
        statusEl.innerText = "Document ready! Choose it from \"Choose Book\".";
        setTimeout(() => (statusEl.innerText = ""), 5000);
      } else if (data.status === "failed") {
        statusEl.innerText = `Processing failed: ${data.error || "unknown error"}`;
      }
    } catch (error) {
      console.error("Error polling document status:", error);
    }
  };
  poll();
}

// --- End document selection functions ---

// TEST mode: Start test by initializing backend state
const startTest = async () => {
  try {
    const res = await fetch("/api/test/start", { method: "POST" });
    const data = await res.json();
    console.log("Test started:", data);
    fetchTestQuestion();
  } catch (error) {
    console.error("Error starting test:", error);
  }
};

// TEST mode: Fetch a test question from the backend and display it
const fetchTestQuestion = async () => {
  try {
    const res = await fetch("/api/test/question");
    const data = await res.json();
    console.log("Fetched Test Question:", data.question);
    if (data.msg && data.msg === "Test Completed") {
      const html = `<div class="message-content">
                      <img src="public/Jurisight.png" alt="logo" class="avatar">
                      <p class="text">Test Completed! Your score: ${data.score} / ${data.max_score}</p>
                    </div>`;
      const resultDiv = createMessageElement(html, "incoming");
      chatList.appendChild(resultDiv);
      chatList.scrollTo(0, chatList.scrollHeight);
      return;
    }
    currentTestQuestionId = data.question_id;
    const html = `<div class="message-content">
                    <img src="public/Jurisight.png" alt="logo" class="avatar">
                    <p class="text"></p>
                  </div>`;
    const incomingQuestionDiv = createMessageElement(html, "incoming");
    incomingQuestionDiv.querySelector(".text").innerText = data.question;
    chatList.appendChild(incomingQuestionDiv);
    chatList.scrollTo(0, chatList.scrollHeight);
  } catch (error) {
    console.error("Error fetching test question:", error);
  }
};

// Toggle interface mode (study/test)
const loadInterfaceMode = () => {
  if (interfaceMode === "test") {
    document.body.classList.add("test-mode");
    toggleInterfaceBtn.innerText = "Switch to Study Mode";
    startTest();
  } else {
    document.body.classList.remove("test-mode");
    toggleInterfaceBtn.innerText = "Switch to Test Mode";
  }
};

loadInterfaceMode();

toggleInterfaceBtn.addEventListener("click", () => {
  if (interfaceMode === "test") {
    interfaceMode = "study";
    localStorage.setItem("interfaceMode", "study");
  } else {
    interfaceMode = "test";
    localStorage.setItem("interfaceMode", "test");
  }
  window.location.reload();
});

// Create a new message element and return it
const createMessageElement = (content, ...classes) => {
  const div = document.createElement("div");
  div.classList.add("message", ...classes);
  div.innerHTML = content;
  return div;
};

// STUDY mode: Fetch a new question from the backend and display it
const fetchQuestion = async () => {
  try {
    const res = await fetch("/api/question");
    const data = await res.json();
    if (!res.ok) {
      console.log("No question available yet:", data.detail);
      return;
    }
    currentQuestionId = data.question_id;
    const html = `<div class="message-content">
                    <img src="public/Jurisight.png" alt="logo" class="avatar">
                    <p class="text"></p>
                  </div>`;
    const incomingQuestionDiv = createMessageElement(html, "incoming");
    incomingQuestionDiv.querySelector(".text").innerText = data.question;
    chatList.appendChild(incomingQuestionDiv);
    chatList.scrollTo(0, chatList.scrollHeight);
  } catch (error) {
    console.error("Error fetching question:", error);
  }
};

document.addEventListener("DOMContentLoaded", () => {
  if (interfaceMode === "study") {
    fetchQuestion();
  }
});

// Handle sending outgoing chat messages
const handleOutgoingChat = () => {
  userMessage = typingForm.querySelector(".typing-input").value.trim() || userMessage;
  if (!userMessage || isResponseGenerating) return;
  isResponseGenerating = true;
  
  const html = `<div class="message-content">
        <img src="public/cat2.png" alt="User Image" class="avatar">
        <p class="text"></p>
      </div>`;
  const outgoingMessageDiv = createMessageElement(html, "outgoing");
  outgoingMessageDiv.querySelector(".text").innerText = userMessage;
  chatList.appendChild(outgoingMessageDiv);
  typingForm.reset();
  chatList.scrollTo(0, chatList.scrollHeight);
  document.body.classList.add("hide-header");
  setTimeout(showLoadingAnimation, 500);
};

// Show typing effect by displaying words one by one. Accepts an optional callback.
const showTypingEffect = (text, textElement, incomingMessageDiv, callback = null) => {
  const words = text.split(' ');
  let currentWordIndex = 0;
  const typingInterval = setInterval(() => {
    textElement.innerText += (currentWordIndex === 0 ? '' : ' ') + words[currentWordIndex++];
    incomingMessageDiv.querySelector(".icon")?.classList.add("hide");
    if (currentWordIndex === words.length) {
      clearInterval(typingInterval);
      isResponseGenerating = false;
      incomingMessageDiv.querySelector(".icon")?.classList.remove("hide");
      if (callback) callback();
    }
    chatList.scrollTo(0, chatList.scrollHeight);
  }, 75);
};

// Fetch response from the backend for answer evaluation (handles both modes)
const generateAPIResponse = async (incomingMessageDiv) => {
  const textElement = incomingMessageDiv.querySelector(".text");
  if (interfaceMode === "study") {
    try {
      const formData = new FormData();
      formData.append("question_id", currentQuestionId);
      formData.append("user_answer", userMessage);
      const response = await fetch("/api/answer", { method: "POST", body: formData });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Error processing answer");
      let apiResponse = data.result;
      if (data.hints) {
        apiResponse += "\nHints: " + data.hints;
      }
      if (data.correct_answer) {
        apiResponse += "\nCorrect Answer: " + data.correct_answer;
      }
      showTypingEffect(apiResponse, textElement, incomingMessageDiv, fetchQuestion);
    } catch (error) {
      isResponseGenerating = false;
      textElement.innerText = error.message;
      textElement.classList.add("error");
    } finally {
      incomingMessageDiv.classList.remove("loading");
    }
  } else {
    try {
      const formData = new FormData();
      formData.append("question_id", currentTestQuestionId);
      formData.append("user_answer", userMessage);
      const response = await fetch("/api/test/answer", { method: "POST", body: formData });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Error processing answer");
      let apiResponse = data.result;
      apiResponse += `\nMarks Awarded: ${data.marks_awarded}\nCurrent Score: ${data.current_score}`;
      showTypingEffect(apiResponse, textElement, incomingMessageDiv, () => {
        if (data.next_question) {
          currentTestQuestionId = data.next_question.question_id;
          const html = `<div class="message-content">
                          <img src="public/Jurisight.png" alt="logo" class="avatar">
                          <p class="text"></p>
                        </div>`;
          const nextQuestionDiv = createMessageElement(html, "incoming");
          nextQuestionDiv.querySelector(".text").innerText = data.next_question.question;
          chatList.appendChild(nextQuestionDiv);
          chatList.scrollTo(0, chatList.scrollHeight);
        } else if (data.msg && data.msg === "Test Completed") {
          const html = `<div class="message-content">
                          <img src="public/Jurisight.png" alt="logo" class="avatar">
                          <p class="text">Test Completed! Your final score is ${data.current_score} / ${data.max_score}</p>
                        </div>`;
          const resultDiv = createMessageElement(html, "incoming");
          chatList.appendChild(resultDiv);
          chatList.scrollTo(0, chatList.scrollHeight);
        }
      });
    } catch (error) {
      isResponseGenerating = false;
      textElement.innerText = error.message;
      textElement.classList.add("error");
    } finally {
      incomingMessageDiv.classList.remove("loading");
    }
  }
};

// Show a loading animation while waiting for the backend response
const showLoadingAnimation = () => {
  const html = `<div class="message-content">
          <img src="public/Jurisight.png" alt="logo" class="avatar">
          <p class="text"></p>
          <div class="loading-indicator">
            <div class="loading-bar"></div>
            <div class="loading-bar"></div>
            <div class="loading-bar"></div>
          </div>
      <span onclick="copyMessage(this)" class="icon material-symbols-rounded">content_copy</span>
      </div>`;
  const incomingMessageDiv = createMessageElement(html, "incoming", "loading");
  chatList.appendChild(incomingMessageDiv);
  chatList.scrollTo(0, chatList.scrollHeight);
  generateAPIResponse(incomingMessageDiv);
};

// Copy message text to the clipboard
const copyMessage = (copyIcon) => {
  const messageText = copyIcon.parentElement.querySelector(".text").innerText;
  navigator.clipboard.writeText(messageText);
  copyIcon.innerText = "done";
  setTimeout(() => copyIcon.innerText = "content_copy", 1000);
};

// Suggestion click handling
suggestions.forEach(suggestion => {
  suggestion.addEventListener("click", () => {
    userMessage = suggestion.querySelector(".text").innerText;
    handleOutgoingChat();
  });
});

// Toggle between light and dark themes
toggleThemeButton.addEventListener("click", () => {
  const isLightMode = document.body.classList.toggle("light_mode");
  localStorage.setItem("themeColor", isLightMode ? "light_mode" : "dark_mode");
  toggleThemeButton.innerText = isLightMode ? "dark_mode" : "light_mode";
});

// Delete chats (simply clears the chat list)
deleteChatButton.addEventListener("click", () => {
  if (confirm("Are you sure you want to delete all messages?")) {
    chatList.innerHTML = "";
  }
});

// Prevent form submission default
typingForm.addEventListener("submit", (e) => {
  e.preventDefault();
  handleOutgoingChat();
});

// File upload handling
document.getElementById("file-upload").addEventListener("change", async function(event) {
  const file = event.target.files[0];
  if (!file) return;

  const statusEl = document.getElementById("upload-status");
  statusEl.innerText = "Uploading…";

  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/documents", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");

    statusEl.innerText = "Processing document…";
    pollDocumentStatus(data.document_id);
  } catch (error) {
    console.error("Error uploading document:", error);
    statusEl.innerText = `Upload failed: ${error.message}`;
  } finally {
    event.target.value = "";
  }
});

// Dummy function for download
function chooseBook() {
  // Instead of a direct download, this function now toggles the dropdown.
  toggleBookDropdown();
}
