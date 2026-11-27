/* Play the supplied sprite-sheet frames without modifying the original image. */
(() => {
  const chick = document.querySelector("#sidebar-chick");
  const lane = chick?.parentElement;
  if (!chick || !lane) return;
  const sprite = chick.querySelector(".chick-sprite");
  if (!sprite) return;
  const frames = {
    walk: Array.from({ length: 4 }, (_, i) => [365 + 271 * i, 10, 185, 115]),
    run: Array.from({ length: 6 }, (_, i) => [390 + 312 * i, 268, 185, 118]),
    fall: Array.from({ length: 6 }, (_, i) => [249 + 328 * i, 540, 250, 174]),
  };
  let motion = "idle", animationTime = 0, drawn = "";
  function setMotion(next) {
    if (motion !== next) { motion = next; animationTime = 0; }
    chick.dataset.motion = next;
  }
  function draw(dt) {
    animationTime += dt;
    // Fall forward, pause on the ground, then replay in reverse to stand up.
    const recovery = [0, 1, 2, 3, 4, 5, 5, 5, 4, 3, 2, 1, 0];
    const index = motion === "fall" ? recovery[Math.min(12, Math.floor(animationTime / .12))]
      : motion === "idle" ? 0 : Math.floor(animationTime / (motion === "run" ? .09 : .16)) % frames[motion].length;
    const action = motion === "idle" ? "walk" : motion;
    const key = `${action}:${index}:${chick.clientWidth}:${chick.clientHeight}`;
    if (key === drawn) return;
    drawn = key;
    const [left, top, width, height] = frames[action][index];
    const scale = Math.min(chick.clientWidth / width, chick.clientHeight / height);
    sprite.style.width = `${width * scale}px`;
    sprite.style.height = `${height * scale}px`;
    sprite.style.left = `${(chick.clientWidth - width * scale) / 2}px`;
    sprite.style.top = `${chick.clientHeight - height * scale}px`;
    sprite.style.backgroundSize = `${2172 * scale}px ${724 * scale}px`;
    sprite.style.backgroundPosition = `${-left * scale}px ${-top * scale}px`;
  }
  let x = 0, target = 0, speed = 24, rest = 0, fallen = false, tripAt = null;
  let previous = performance.now();
  let frameRequest;
  let enabled = true;
  const toggle = document.querySelector("#chick-enabled-toggle");
  try { enabled = localStorage.getItem("mainflow.chickEnabled") !== "false"; } catch {}
  lane.hidden = !enabled;
  if (toggle?.addEventListener) {
    toggle.checked = enabled;
    toggle.addEventListener("change", () => {
      enabled = toggle.checked;
      lane.hidden = !enabled;
      try { localStorage.setItem("mainflow.chickEnabled", String(enabled)); } catch {}
      cancelAnimationFrame(frameRequest);
      if (enabled) {
        previous = performance.now();
        frameRequest = requestAnimationFrame(frame);
      }
    });
  }
  function chooseTrip() {
    const width = Math.max(0, lane.clientWidth - chick.clientWidth);
    target = Math.random() * width;
    if (Math.abs(target - x) < 30) target = x < width / 2 ? width : 0;
    const running = Math.random() < .5;
    speed = running ? 72 : 24;
    setMotion(running ? "run" : "walk");
    chick.style.setProperty("--facing", target >= x ? "1" : "-1");
    fallen = false;
    tripAt = running && Math.random() < .08 ? x + (target - x) * (.35 + Math.random() * .3) : null;
  }
  function frame(now) {
    if (!enabled) return;
    const elapsed = Math.max(0, (now - previous) / 1000);
    const dt = Math.min(elapsed, .05); previous = now;
    if (!document.hidden) {
      const edge = Math.max(0, lane.clientWidth - chick.clientWidth);
      x = Math.min(x, edge); target = Math.min(target, edge);
      if (rest > 0) {
        rest -= elapsed;
        if (rest <= 0) {
          if (fallen) { setMotion("run"); fallen = false; }
          else chooseTrip();
        }
      } else {
        const direction = Math.sign(target - x);
        const next = x + direction * Math.min(Math.abs(target - x), speed * dt);
        if (tripAt !== null && (tripAt - x) * (tripAt - next) <= 0) {
          tripAt = null; fallen = true; rest = 1.56; setMotion("fall");
        } else {
          x = next;
          if (Math.abs(target - x) < 1) chooseTrip();
        }
      }
    }
    draw(document.hidden ? 0 : dt);
    chick.style.transform = `translateX(${x}px)`;
    frameRequest = requestAnimationFrame(frame);
  }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden || !enabled) return;
    cancelAnimationFrame(frameRequest);
    previous = performance.now();
    if (!fallen) chooseTrip();
    frameRequest = requestAnimationFrame(frame);
  });
  draw(0);
  chooseTrip();
  if (enabled) frameRequest = requestAnimationFrame(frame);
})();
