"use strict";
const list = document.querySelector("#links");
const count = document.querySelector("#count");
const message = document.querySelector("#message");
const search = document.querySelector("#search");
let links = [];

function render() {
  const query = search.value.trim().toLocaleLowerCase();
  const visible = links.filter(link => `${link.name} ${link.description}`.toLocaleLowerCase().includes(query));
  list.replaceChildren();
  for (const link of visible) {
    const card = document.createElement("a");
    card.className = "card";
    card.href = link.url;
    card.target = "_blank";
    card.rel = "noopener noreferrer";
    const top = document.createElement("div");
    top.className = "card-top";
    const icon = document.createElement("span");
    icon.className = "icon";
    icon.textContent = link.name[0].toLocaleUpperCase();
    icon.setAttribute("aria-hidden", "true");
    const arrow = document.createElement("span");
    arrow.className = "arrow";
    arrow.textContent = "↗";
    arrow.setAttribute("aria-hidden", "true");
    top.append(icon, arrow);
    const title = document.createElement("h3");
    title.textContent = link.name;
    const description = document.createElement("p");
    description.textContent = link.description;
    card.append(top, title, description);
    list.append(card);
  }
  count.textContent = `Ссылок: ${visible.length} из ${links.length}`;
  message.hidden = visible.length !== 0;
  message.textContent = "Ничего не найдено. Попробуй другое название.";
}

async function load() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error("Configuration unavailable");
    const config = await response.json();
    document.title = config.title;
    document.querySelector("#brand-title").textContent = config.title;
    links = config.links;
    render();
  } catch {
    count.textContent = "Ссылки недоступны";
    message.hidden = false;
    message.textContent = "Не удалось загрузить конфигурацию. Попробуй обновить страницу позже.";
    search.disabled = true;
  }
  try {
    const response = await fetch("/api/info");
    if (response.ok) {
      const info = await response.json();
      document.querySelector("#version").textContent = `Версия ${info.version}`;
    }
  } catch { /* The links remain useful when the version endpoint is unavailable. */ }
}
search.addEventListener("input", render);
load();
