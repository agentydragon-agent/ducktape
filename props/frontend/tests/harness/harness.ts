// Component harness for visual regression testing
// Mounts components based on URL parameters

import { mount } from "svelte";
import "../../src/app.css";

// Import components for testing
import BackButton from "../../src/components/BackButton.svelte";
import Breadcrumb from "../../src/components/Breadcrumb.svelte";
import CopyButton from "../../src/components/CopyButton.svelte";

// Component registry with their test scenarios
const components: Record<string, { component: any; scenarios: Record<string, Record<string, unknown>> }> = {
  BackButton: {
    component: BackButton,
    scenarios: {
      Default: {},
      CustomLabel: { label: "← Go Back" },
      CustomHref: { href: "/custom-path", label: "← Return" },
      CustomClass: { class: "text-lg text-blue-600 hover:text-blue-800 font-semibold", label: "← Styled Back" },
    },
  },
  Breadcrumb: {
    component: Breadcrumb,
    scenarios: {
      SingleItem: { items: [{ label: "snapshot-name" }] },
      WithPath: {
        items: [
          { label: "snapshot-name", href: "/snapshots/snapshot-name" },
          { label: "src" },
          { label: "components" },
          { label: "Button.tsx" },
        ],
      },
      DeepPath: {
        items: [
          { label: "snapshot-name", href: "/snapshots/snapshot-name" },
          { label: "src" },
          { label: "features" },
          { label: "auth" },
          { label: "components" },
          { label: "LoginForm.tsx" },
        ],
      },
      AllLinked: {
        items: [
          { label: "Home", href: "/" },
          { label: "Snapshots", href: "/snapshots" },
          { label: "snapshot-1", href: "/snapshots/snapshot-1" },
          { label: "file.py" },
        ],
      },
    },
  },
  CopyButton: {
    component: CopyButton,
    scenarios: {
      Default: { text: "https://example.com/some/url/to/copy" },
      CustomLabel: { text: "console.log('Hello, World!');", label: "Copy Code" },
      CustomSuccessMessage: {
        text: "git clone https://github.com/example/repo.git",
        label: "Copy",
        successMessage: "Git command copied!",
      },
      LongText: {
        text: "https://example.com/very/long/url/that/might/need/to/be/copied/for/deep/linking/purposes",
        label: "Copy URL",
      },
    },
  },
};

// Parse URL parameters
const params = new URLSearchParams(window.location.search);
const componentName = params.get("component");
const scenarioName = params.get("scenario") || "Default";

const app = document.getElementById("app")!;

if (!componentName) {
  // Show available components and scenarios
  app.innerHTML = `
    <div style="font-family: system-ui; padding: 20px;">
      <h1>Component Harness</h1>
      <p>Available components and scenarios:</p>
      <ul>
        ${Object.entries(components)
          .map(
            ([name, { scenarios }]) => `
          <li>
            <strong>${name}</strong>
            <ul>
              ${Object.keys(scenarios)
                .map((s) => `<li><a href="?component=${name}&scenario=${s}">${s}</a></li>`)
                .join("")}
            </ul>
          </li>
        `
          )
          .join("")}
      </ul>
    </div>
  `;
} else if (!components[componentName]) {
  app.innerHTML = `<div style="color: red;">Unknown component: ${componentName}</div>`;
} else {
  const { component, scenarios } = components[componentName];
  const props = scenarios[scenarioName];

  if (!props) {
    app.innerHTML = `<div style="color: red;">Unknown scenario: ${scenarioName} for ${componentName}</div>`;
  } else {
    // Mount the component with props
    mount(component, {
      target: app,
      props,
    });
  }
}
