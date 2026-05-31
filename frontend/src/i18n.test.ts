import { describe, expect, it } from "vitest";

import { defaultLanguage } from "./i18n";

describe("i18n", () => {
  it("uses Spanish as the default language", () => {
    expect(defaultLanguage).toBe("es");
  });
});
