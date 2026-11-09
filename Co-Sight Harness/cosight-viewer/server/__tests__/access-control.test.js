// SPDX-License-Identifier: Apache-2.0
/**
 * @file Tests for the file-access policy.
 *
 * Default is open (LAN pages can preview files); VIEWER_FS_LOCAL_ONLY=1
 * restricts /fs and /session-files to loopback clients.
 */

const { describe, it, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");

const {
  isLoopbackAddress,
  isLoopback,
  isLocalOnlyEnabled,
  allowRequest,
} = require("../lib/access-control");

let saved;

beforeEach(() => {
  saved = process.env.VIEWER_FS_LOCAL_ONLY;
  delete process.env.VIEWER_FS_LOCAL_ONLY;
});

afterEach(() => {
  if (saved === undefined) delete process.env.VIEWER_FS_LOCAL_ONLY;
  else process.env.VIEWER_FS_LOCAL_ONLY = saved;
});

function reqWith(address) {
  return { socket: { remoteAddress: address } };
}

describe("isLoopbackAddress()", () => {
  it("recognises IPv4/IPv6 loopback", () => {
    assert.equal(isLoopbackAddress("127.0.0.1"), true);
    assert.equal(isLoopbackAddress("::1"), true);
    assert.equal(isLoopbackAddress("::ffff:127.0.0.1"), true);
    assert.equal(isLoopbackAddress("203.0.113.90"), false);
    assert.equal(isLoopbackAddress(""), false);
  });

  it("isLoopback() only trusts the socket peer", () => {
    assert.equal(isLoopback(reqWith("127.0.0.1")), true);
    assert.equal(isLoopback(reqWith("203.0.113.90")), false);
    assert.equal(isLoopback({}), false);
  });
});

describe("allowRequest()", () => {
  it("allows remote clients by default", () => {
    assert.equal(isLocalOnlyEnabled(), false);
    assert.equal(allowRequest(reqWith("203.0.113.90")), true);
    assert.equal(allowRequest(reqWith("127.0.0.1")), true);
  });

  it("restricts to loopback when VIEWER_FS_LOCAL_ONLY=1", () => {
    process.env.VIEWER_FS_LOCAL_ONLY = "1";
    assert.equal(isLocalOnlyEnabled(), true);
    assert.equal(allowRequest(reqWith("203.0.113.90")), false);
    assert.equal(allowRequest(reqWith("127.0.0.1")), true);
  });

  it("accepts true/yes/on and ignores false-y values", () => {
    for (const value of ["true", "YES", "on"]) {
      process.env.VIEWER_FS_LOCAL_ONLY = value;
      assert.equal(allowRequest(reqWith("10.0.0.1")), false, value);
    }
    for (const value of ["0", "false", "off", ""]) {
      process.env.VIEWER_FS_LOCAL_ONLY = value;
      assert.equal(allowRequest(reqWith("10.0.0.1")), true, value);
    }
  });
});
