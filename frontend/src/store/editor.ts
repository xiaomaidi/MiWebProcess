import { defineStore } from "pinia";

export type Device = "desktop" | "tablet" | "phone";

export const DEVICE_WIDTHS: Record<Device, number> = {
  desktop: 1200,
  tablet: 768,
  phone: 375,
};

export const useEditorStore = defineStore("editor", {
  state: () => ({
    device: "desktop" as Device,
    zoom: 1,
    /** 递增令牌：设计器工具栏点击「适应」时通知画布重新计算缩放。 */
    fitRequest: 0,
    gridEnabled: true,
    gridSize: 8,
    leftTab: "components" as "components" | "outline" | "datasources",
    rightTab: "props" as "props" | "style" | "events" | "binding" | "condition" | "slots",
    leftOpen: true,
    rightOpen: true,
    saveStatus: "saved" as "saved" | "dirty" | "saving" | "error" | "conflict",
    lastSavedAt: "",
  }),
  actions: {
    setDevice(d: Device) {
      this.device = d;
    },
    setZoom(z: number) {
      this.zoom = Math.min(2, Math.max(0.25, z));
    },
    requestFit() {
      this.fitRequest += 1;
    },
  },
});
