/// <reference types="@testing-library/jest-dom" />

// @testing-library/jest-dom v6 ships its own matcher types, which augment
// jest.Matchers via the reference above. This file used to redeclare that
// interface by hand; the copy had drifted (its toHaveClass took a single
// class name, and it declared Matchers with one type parameter where jest-dom
// uses two, so the real declarations never merged). The result was a repo that
// failed `tsc` on assertions that pass at runtime — which kept the Node CI job
// red and stopped the Jest suite from ever running there.
//
// Add nothing here unless it is a genuinely custom matcher.
