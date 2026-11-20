"""Test client for the auth node. Start the auth node first, then:

    python -m services.auth.test_auth
"""
import sys

import grpc

from protos import enrollment_pb2 as pb
from protos import enrollment_pb2_grpc as rpc
from common import config, jwt_util

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def main():
    stub = rpc.AuthServiceStub(grpc.insecure_channel(config.AUTH_ADDR))
    login = lambda u, p: stub.Login(pb.LoginRequest(username=u, password=p), timeout=config.RPC_TIMEOUT)

    print(f"Testing AuthService at {config.AUTH_ADDR}")
    try:
        r = login("student1", "password")
    except grpc.RpcError as e:
        print(f"  Can't reach auth node ({e.code().name}). Is the auth node running? (python -m services.auth.server)")
        sys.exit(1)

    check("student login ok", r.ok and r.role == "student", r.msg)
    claims = jwt_util.claims_or_none(r.jwt)
    check("student token verifies locally", claims is not None)
    check("token has right user and role",
          claims is not None and claims["sub"] == "student1" and claims["role"] == "student", str(claims))

    r = login("faculty1", "password")
    check("faculty login ok", r.ok and r.role == "faculty", r.msg)
    claims = jwt_util.claims_or_none(r.jwt)
    check("faculty token has faculty role", claims is not None and claims["role"] == "faculty")

    r = login("student1", "wrong")
    check("wrong password rejected", not r.ok and r.jwt == "", r.msg)

    r = login("nobody", "password")
    check("unknown user rejected", not r.ok and r.jwt == "", r.msg)

    r = login("", "")
    check("empty credentials rejected", not r.ok, r.msg)

    check("tampered token rejected", jwt_util.claims_or_none(login("student1", "password").jwt + "x") is None)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
