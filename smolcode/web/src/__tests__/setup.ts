import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, expect } from 'vitest';
import * as axeMatchers from 'vitest-axe/matchers';

// vitest-axe ships the matcher as a plain function; expect.extend accepts { name: fn } records.
// We pass it through with a type cast because the runtime signature differs slightly from vitest's.
expect.extend(axeMatchers as unknown as Parameters<typeof expect.extend>[0]);

// Augment vitest's Assertion type so `expect(results).toHaveNoViolations()` typechecks.
declare module 'vitest' {
  interface Assertion<T> {
    toHaveNoViolations(): T
  }
}

// Auto-cleanup DOM after each test (unmount React trees).
afterEach(() => {
  cleanup();
});

// Mock matchMedia for components that read media queries.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// Mock ResizeObserver (some components depend on it).
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;