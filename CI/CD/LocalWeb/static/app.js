const statusDot = document.querySelector("#status-dot");
const statusText = document.querySelector("#status-text");

async function checkServerHealth() {
  try {
    const response = await fetch("/api/health", {
      headers: { Accept: "application/json" },
    });

    if (!response.ok) {
      throw new Error(`health check failed: ${response.status}`);
    }

    const health = await response.json();
    statusDot.className = "status-dot status-dot--ready";
    statusText.textContent =
      health.workflow === "not_connected"
        ? "로컬 서버 정상 · Workflow 연결 전"
        : "로컬 서버 정상";
  } catch (error) {
    statusDot.className = "status-dot status-dot--error";
    statusText.textContent = "로컬 서버 상태를 확인할 수 없습니다.";
    console.error(error);
  }
}

checkServerHealth();
