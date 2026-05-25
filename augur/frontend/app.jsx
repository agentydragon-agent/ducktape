import React from "react";
import { MantineProvider } from "@mantine/core";

import ProductProjectionAppShell from "./product_app.jsx";

export default function AugurApp() {
  return (
    <MantineProvider defaultColorScheme="auto">
      <ProductProjectionAppShell />
    </MantineProvider>
  );
}
