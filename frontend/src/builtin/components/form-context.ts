/**
 * wp-form 通过 provide 暴露给后代表单字段组件
 * （wp-input/wp-textarea/wp-select/wp-checkbox/wp-radio/wp-switch/wp-number/wp-date）。
 * 注入键为 "wp.form"，scope=null 时组件仍可独立渲染。
 */
export interface WpFormContext {
  /** 字段值集合（reactive）：字段名 → 值。 */
  values: Record<string, any>;
  /** 字段组件回写值。 */
  setField(field: string, value: any): void;
  /** 登记字段及其初始值（首次登记生效，reset 时还原）。 */
  register(field: string, value: any): void;
  /** 还原所有字段到登记时的初始值。 */
  reset(): void;
  /** 触发表单校验（Element Plus Form.validate）；无校验时 resolve(true)。 */
  validate?(): Promise<boolean>;
  /** wp-form.disabled。 */
  readonly disabled: boolean;
  /** wp-form.inline。 */
  readonly inline: boolean;
  /** wp-form.labelWidth。 */
  readonly labelWidth: number;
  /** wp-form.labelPosition。 */
  readonly labelPosition: "right" | "top";
}

export const wpFormContextKey: symbol = Symbol("wp.form");
