/// <reference types="@testing-library/jest-dom" />

declare namespace jest {
  interface Matchers<R> {
    toBeInTheDocument(): R;
    toHaveValue(value: string | number): R;
    toHaveTextContent(text: string | RegExp): R;
    toHaveClass(className: string): R;
    toBeVisible(): R;
    toBeChecked(): R;
    toBeDisabled(): R;
    toBeEnabled(): R;
    toBeEmptyDOMElement(): R;
    toBeInvalid(): R;
    toBeRequired(): R;
    toBeValid(): R;
    toContainElement(element: HTMLElement | null): R;
    toContainHTML(htmlText: string): R;
    toHaveAttribute(attr: string, value?: string): R;
    toHaveDisplayValue(value: string | RegExp | (string | RegExp)[]): R;
    toHaveFocus(): R;
    toHaveFormValues(expectedValues: Record<string, any>): R;
    toHaveStyle(css: Record<string, any> | string): R;
    toHaveAccessibleDescription(expectedDescription?: string | RegExp): R;
    toHaveAccessibleName(expectedName?: string | RegExp): R;
    toHaveErrorMessage(expectedErrorMessage?: string | RegExp): R;
  }
}