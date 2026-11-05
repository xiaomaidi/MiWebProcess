/**
 * Demo market component for sandbox/signing verification.
 * Runs inside an opaque-origin iframe; no access to the parent app.
 */
class WpMarketDemo extends HTMLElement {
  static get observedAttributes() {
    return ["title", "value"];
  }
  connectedCallback() {
    this.render();
  }
  attributeChangedCallback() {
    this.render();
  }
  render() {
    const title = this.getAttribute("title") || "Sandbox component";
    const value = this.getAttribute("value") || "128";
    this.innerHTML = `
      <div style="font-family:system-ui,sans-serif;border:1px solid #dbe5f1;border-radius:14px;padding:18px;background:#fff;color:#0f172a">
        <div style="font-size:12px;color:#64748b">${title}</div>
        <div style="font-size:30px;font-weight:800;margin-top:8px">${value}</div>
        <div style="margin-top:8px;font-size:11px;color:#16a34a">sandboxed custom element</div>
      </div>`;
  }
}
if (!customElements.get("wp-market-demo")) {
  customElements.define("wp-market-demo", WpMarketDemo);
}
