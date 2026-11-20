"""Generate protos/enrollment_pb2.py and protos/enrollment_pb2_grpc.py.
Run from the project root:  python gen_protos.py   (works on Windows/Mac/Linux)

Import them anywhere as:
    from protos import enrollment_pb2 as pb, enrollment_pb2_grpc as rpc
"""
import sys

from grpc_tools import protoc

rc = protoc.main([
    "grpc_tools.protoc",
    "-I.",                       # proto path = project root, so generated code imports "from protos import ..."
    "--python_out=.",
    "--grpc_python_out=.",
    "protos/enrollment.proto",
])
if rc != 0:
    sys.exit(rc)
print("Generated protos/enrollment_pb2.py and protos/enrollment_pb2_grpc.py")
