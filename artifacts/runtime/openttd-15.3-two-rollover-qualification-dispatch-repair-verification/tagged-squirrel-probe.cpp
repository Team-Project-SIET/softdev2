#include "/tmp/OpenTTD-15.3/src/stdafx.h"
#include "/tmp/OpenTTD-15.3/src/3rdparty/squirrel/include/squirrel.h"
#include <fstream>
#include <iostream>
int main(int argc,char **argv){std::ifstream f(argv[1]);std::string code((std::istreambuf_iterator<char>(f)),{});auto v=sq_open(1024);sq_pushroottable(v);if(SQ_FAILED(sq_compilebuffer(v,code,"probe",true))){std::cerr<<"compile failed\n";return 2;}sq_pushroottable(v);if(SQ_FAILED(sq_call(v,1,false,true))){sq_getlasterror(v);std::string_view e;sq_getstring(v,-1,e);std::cerr<<e<<"\n";return 1;}std::cout<<"PASS\n";sq_close(v);}
void *sq_vm_malloc(SQUnsignedInteger n){return malloc(n);}
void *sq_vm_realloc(void *p,SQUnsignedInteger,SQUnsignedInteger n){return realloc(p,n);}
void sq_vm_free(void *p,SQUnsignedInteger){free(p);}
[[noreturn]] void NOT_REACHED(std::source_location){abort();}
void DebugPrint(std::string_view,int,std::string &&){}
