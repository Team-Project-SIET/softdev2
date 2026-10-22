/* Standalone host for OpenTTD 15.3's unmodified Squirrel VM; no game/network. */
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <squirrel.h>
#include "sqpcheader.h"
#include "sqvm.h"

static int commands = 0;

static void CompileError(HSQUIRRELVM, std::string_view message,
        std::string_view, SQInteger line, SQInteger column)
{
    fprintf(stderr, "compile %lld:%lld %.*s\n", (long long)line,
        (long long)column, (int)message.size(), message.data());
}

static SQInteger Command(HSQUIRRELVM vm)
{
    // Same gate used by ScriptObject::CanSuspend before DoCommand.
    if (!sq_can_suspend(vm)) return sq_throwerror(vm, "COMMAND_NOT_SUSPENDABLE");
    if (sq_gettop(vm) > 1) {
        std::string_view mode;
        sq_getstring(vm, 2, mode);
        if (mode == "error") return sq_throwerror(vm, "NATIVE_COMMAND_ERROR");
    }
    ++commands;
    return sq_suspendvm(vm);
}

[[noreturn]] static void Fail(HSQUIRRELVM vm)
{
    sq_getlasterror(vm);
    std::string_view message;
    sq_getstring(vm, -1, message);
    fprintf(stderr, "%.*s\n", (int)message.size(), message.data());
    exit(1);
}

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    std::ifstream input(argv[1]);
    if (!input) return 2;
    std::ostringstream buffer;
    buffer << input.rdbuf();
    auto source = buffer.str();
    auto vm = sq_open(1024);
    sq_setcompilererrorhandler(vm, CompileError);
    sq_pushroottable(vm);
    sq_pushstring(vm, "NativeCommand");
    sq_newclosure(vm, Command, 0);
    sq_newslot(vm, -3, SQFalse);
    sq_pop(vm, 1);
    if (SQ_FAILED(sq_compilebuffer(vm, source, "startup", SQTrue))) Fail(vm);
    sq_pushroottable(vm);
    if (SQ_FAILED(sq_call(vm, 1, SQFalse, SQTrue, 1000000))) Fail(vm);
    while (sq_getvmstate(vm) == SQ_VMSTATE_SUSPENDED) {
        if (commands > 500) {
            fprintf(stderr, "COMMAND_BUDGET\n");
            return 1;
        }
        // Squirrel::InsertResult followed by Squirrel::Resume after completion.
        sq_pushbool(vm, SQTrue);
        vm->GetAt(vm->_stackbase + vm->_suspended_target) = vm->GetUp(-1);
        vm->Pop();
        if (!sq_resumecatch(vm, 1000000)) Fail(vm);
    }
    printf("suspended/resumed commands=%d\n", commands);
    sq_close(vm);
}

// Embedding allocator only; VM and parser sources remain unmodified.
void *sq_vm_malloc(size_t size) { return std::malloc(size); }
void *sq_vm_realloc(void *pointer, size_t, size_t size) { return std::realloc(pointer, size); }
void sq_vm_free(void *pointer, size_t) { std::free(pointer); }
void DebugPrint(std::string_view, int, std::string &&message)
{
    fprintf(stderr, "%s\n", message.c_str());
}
[[noreturn]] void NOT_REACHED(std::source_location) { std::abort(); }
