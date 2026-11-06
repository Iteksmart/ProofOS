import React from "react";
import { healthClass } from "./tokens.js";

export function HealthPill({ status }) {
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs border ${healthClass(status)}`}>
      {status}
    </span>
  );
}
