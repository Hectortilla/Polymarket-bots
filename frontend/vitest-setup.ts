import '@testing-library/jest-dom/vitest';

// Svelte Flow expects these browser APIs, which jsdom does not implement.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => true
    }) as MediaQueryList
});

globalThis.ResizeObserver ??= class implements ResizeObserver {
  disconnect(): void {}
  observe(): void {}
  unobserve(): void {}
};
