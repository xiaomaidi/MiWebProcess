<template>
  <div class="wp-geo-picker">
    <div ref="mapEl" class="wp-geo-map" />
    <div class="wp-geo-fields">
      <label>
        纬度
        <el-input-number v-model="lat" :precision="6" :controls="false" size="small" style="width: 100%" />
      </label>
      <label>
        经度
        <el-input-number v-model="lng" :precision="6" :controls="false" size="small" style="width: 100%" />
      </label>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const props = withDefaults(defineProps<{ modelValue?: { lat?: number; lng?: number } | null }>(), { modelValue: null });
const emit = defineEmits<{ "update:modelValue": [value: { lat: number; lng: number }] }>();
const mapEl = ref<HTMLElement | null>(null);
const lat = ref<number>(Number(props.modelValue?.lat ?? 30.2741));
const lng = ref<number>(Number(props.modelValue?.lng ?? 120.1551));
let map: L.Map | null = null;
let marker: L.CircleMarker | null = null;

function setMarker(nextLat: number, nextLng: number) {
  if (!map) return;
  if (!marker) {
    marker = L.circleMarker([nextLat, nextLng], {
      radius: 8, color: "#ffffff", weight: 3, fillColor: "#2563eb", fillOpacity: 1,
    }).addTo(map);
  } else {
    marker.setLatLng([nextLat, nextLng]);
  }
}
function emitValue() {
  emit("update:modelValue", { lat: Number(lat.value), lng: Number(lng.value) });
}
function initMap() {
  if (!mapEl.value || map) return;
  map = L.map(mapEl.value, { zoomControl: false, attributionControl: true }).setView([lat.value, lng.value], 12);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);
  setMarker(lat.value, lng.value);
  map.on("click", (event: L.LeafletMouseEvent) => {
    lat.value = Number(event.latlng.lat.toFixed(6));
    lng.value = Number(event.latlng.lng.toFixed(6));
    setMarker(lat.value, lng.value);
    emitValue();
  });
  setTimeout(() => map?.invalidateSize(), 50);
}
watch([lat, lng], () => {
  setMarker(lat.value, lng.value);
  map?.panTo([lat.value, lng.value], { animate: false });
});
watch(
  () => props.modelValue,
  (value) => {
    if (!value) return;
    if (Number(value.lat) !== lat.value) lat.value = Number(value.lat);
    if (Number(value.lng) !== lng.value) lng.value = Number(value.lng);
  },
  { deep: true }
);
onMounted(async () => {
  await nextTick();
  initMap();
});
onBeforeUnmount(() => {
  map?.remove();
  map = null;
  marker = null;
});
</script>

<style scoped>
.wp-geo-picker { width: 100%; border: 1px solid #dbe3ef; border-radius: 8px; overflow: hidden; background: #fff; }
.wp-geo-map { height: 190px; width: 100%; z-index: 0; background-color: #eef4f8; background-image: linear-gradient(#dbe7f0 1px, transparent 1px), linear-gradient(90deg, #dbe7f0 1px, transparent 1px); background-size: 32px 32px; }
.wp-geo-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 8px; }
.wp-geo-fields label { color: #64748b; font-size: 10px; }
:deep(.leaflet-control-attribution) { font-size: 8px; }
</style>
