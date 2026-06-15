function renderMarkdown(text) {
  return DOMPurify.sanitize(marked.parse(text || '', { breaks: true }));
}
