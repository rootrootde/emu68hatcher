(() => {
  const links = [...document.querySelectorAll(".md-content a[href] > img")]
    .map((image) => image.parentElement)
    .filter((link) => /\.(avif|gif|jpe?g|png|webp)$/i.test(new URL(link.href).pathname));

  if (!links.length) return;

  const dialog = document.createElement("dialog");
  if (typeof dialog.showModal !== "function") return;
  dialog.className = "image-lightbox";
  dialog.setAttribute("aria-label", "Image preview");

  const frame = document.createElement("figure");
  frame.className = "image-lightbox__frame";

  const image = document.createElement("img");
  image.className = "image-lightbox__image";

  const caption = document.createElement("figcaption");
  caption.className = "image-lightbox__caption";

  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "image-lightbox__close";
  closeButton.setAttribute("aria-label", "Close image preview");
  closeButton.textContent = "×";

  frame.append(image, caption, closeButton);
  dialog.append(frame);
  document.body.append(dialog);

  const close = () => {
    if (dialog.open) dialog.close();
  };

  closeButton.addEventListener("click", close);
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close();
  });
  dialog.addEventListener("close", () => {
    image.removeAttribute("src");
    image.alt = "";
    caption.textContent = "";
  });

  links.forEach((link) => {
    const preview = link.querySelector("img");
    link.classList.add("image-lightbox-link");
    link.addEventListener("click", (event) => {
      event.preventDefault();
      image.src = link.href;
      image.alt = preview.alt;
      caption.textContent = preview.alt;
      caption.hidden = !preview.alt;
      dialog.showModal();
    });
  });
})();
