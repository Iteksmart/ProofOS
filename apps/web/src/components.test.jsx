import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { describe, it, expect } from "vitest";
import { ProofBadge, HealthPill, DeviceCard, TicketRow } from "@proofos/ui";

describe("HealthPill", () => {
  it("renders the status label", () => {
    render(<HealthPill status="online" />);
    expect(screen.getByText("online")).toBeInTheDocument();
  });
});

describe("ProofBadge", () => {
  it("shows verified for true", () => {
    render(<ProofBadge verified={true} />);
    expect(screen.getByText(/verified/)).toBeInTheDocument();
  });
  it("shows unchecked for null (never 'invalid')", () => {
    render(<ProofBadge verified={null} />);
    expect(screen.getByText(/unchecked/)).toBeInTheDocument();
  });
});

describe("DeviceCard", () => {
  it("renders hostname and metrics", () => {
    render(
      <DeviceCard device={{ hostname: "ws-01", os: "Linux", ip: "10.0.0.1", status: "online", cpu: 10, disk: 20, mem: 30 }} />
    );
    expect(screen.getByText("ws-01")).toBeInTheDocument();
    expect(screen.getByText(/10\.0\.0\.1/)).toBeInTheDocument();
  });
});

describe("TicketRow", () => {
  it("renders the ticket title", () => {
    render(<TicketRow ticket={{ id: 1, title: "printer down", status: "open", priority: "high" }} />);
    expect(screen.getByText("printer down")).toBeInTheDocument();
  });
});
