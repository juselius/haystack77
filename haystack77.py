#!/usr/bin/env python
#
# Written by Jonas Juselius <jonas@iki.fi>
#

import sys, re, string
import os.path
import shelve
import getopt

inclist_ignore=['implicit.h', 'priunit.h', 'dummy.h']

class FortParser:
    newline=re.compile('\n')
    f90cont=re.compile('(.*?)&\s*$')
    linecont=re.compile('     \S(.*)') # maybe fix for .F files?
    discard=re.compile('([cC]+|\s*!.*|\s*$)')
    inline_comment=re.compile('(.*?)!')

    def_w_args=re.compile('\s*(\S*?)\s*\((.*?)\)\s*(?:!.*)?$')
    def_wo_args=re.compile('\s*(\S*?)\s*(?:!.*)?$')

    fort_common=re.compile('\s*common\s*\/(\w+)\/(.*)', re.I)
    fort_include=re.compile('\s*#include\s*(?:"|<)\s*(.+)\s*(?:"|>)', re.I)
#    fort_include=re.compile('\s*#include(.*)', re.I)
#    fort_include=re.compile('\s*#include\s*(?:"|<)(\w+)(?:"|>)\s*', re.I)

    subroutine_def=re.compile('\s*?(?:subroutine|program|(?:(?:(?:integer|real|logical)(?:\*[48])?)|double|)?(?:\s*precision)?\s*function)\s*(\w+)\s*(?:\((.*)\)|(.*)(?!\))\s*$)', re.I)

    fort_call=re.compile('(?:\s*|\s*[0-9]*\s*)call\s*(\w+)\s*\(?(.*)\)?', re.I)

    def __init__(self, buf):
        self.buf=buf

    def parse(self, filebuf):
        buf=self.sanitize(filebuf)
        currsub=None
        subs={}
        for i in buf:
            sub=self.parse_sub_def(i)
            if sub is not None:
                if currsub is not None: # save the previous subroutine
                    currsub.filter_includes(inclist_ignore)
                    subs[currsub.name]=currsub
                currsub=FortSubroutine(sub[0],sub[1])
                continue

            call=self.parse_call(i)
            if call is not None:
                currsub[call[0]]=call[1]
                continue

            comn=self.parse_common_block(i)

            if comn is not None:
#                print comn[0],'--',comn[1]
                currsub.add_common_block(comn)
                continue

            incl=self.parse_include(i)
            if incl is not None:
                if currsub is not None:
                    currsub.add_include(incl)
                continue
        return subs

    def parse_sub_def(self,i):
        mob=self.subroutine_def.match(i)
        if mob:
            return self.sift(mob)
        return None

    def parse_call(self, i):
        mob=self.fort_call.match(i)
        if mob:
            return self.sift(mob)
        return None

    def parse_common_block(self, i):
        mob=self.fort_common.match(i)
        if mob:
            return self.sift(mob)
        return None

    def parse_include(self, i):
        mob=self.fort_include.match(i)
        if mob:
            return mob.group(1)
        return None

    def sift(self, mob):
        '''Sift arguments, and separate variables from cruft'''
        name=mob.group(1)
        if mob.lastindex == 2:
            args=mob.group(2)
            args=string.split(args,',')
            args=map(string.strip, args)
        else:
            args=[]
        print name,'--',args
        return (name, args)

    def sanitize(self, buf):
        """
        Try to sanitize the source, to make it parsable using simple regular
        expressions; remove empty lines and comments, and join lines with
        continuations.
        """
        lines=[]
        pos=0
        while (pos < len(buf)-1):
            #discard empty and comment lines
            if self.discard.match(buf[pos]):
                pos+=1
                continue
            # remove any inline f90 comments
            x=self.inline_comment.match(buf[pos])
            if x is not None:
                buf[pos]=x.group(1)

            x=self.f90cont.match(buf[pos])
            if x is not None:
                buf[pos]=x.group(1) # strip the &
                x=self.linecont.match(buf[pos+1])
                if x is not None:
                    buf[pos+1]='     &'+pub[pos+1]

            # we can have both types of continuations
            buf[pos]=self.newline.sub('',buf[pos])
            x=self.linecont.match(buf[pos])
            if x is not None:
#                print "linecont:",buf[pos],"->", lines[-1]
                buf[pos]=x.group(1)
                lines[-1]=lines[-1]+buf[pos]
            else:
                lines.append(buf[pos])

            pos+=1
        return lines

def parse_file(filename):
    try:
        fd=open(filename, 'r')
    except:
        print "Error: no such file ", filename
        buf=[]
    else:
        buf=fd.readlines()
        fd.close()

    fp=FortParser(buf)
    subs=fp.parse(buf)
    return FortFile(filename,subs)

class Common:
    # ugly, very ugly...
    def has_arg(self, arg):
        apa=re.compile(arg, re.I)
        apa2=re.compile('\(.*?'+arg+'.*?\)')
        for i in range(len(self.args)):
            if apa.search(self.args[i]):
                if not apa2.search(self.args[i]):
                    return i
        return None

class FortFile:
    def __init__(self, filename, subroutines={}):
        self.filename=filename
        self.subs=subroutines

    def __getitem__(self, name):
        return self.subs[name]

    def keys(self):
        return self.subs.keys()

    def has_key(self, key):
        return self.subs.has_key(key)

    def __str__(self):
        print self.filename
        print '++++++++++++++++++++++++++++++'
        for i in self.subs:
            print self.subs[i]
        return 'end of ' + self.filename

    def dotty(self):
        for i in self.subs:
            print "\"%s\" -> \"%s\";" % (self.filename, i)
            self.subs[i].dotty()

class FortSubroutine(Common):
    def __init__(self, name, args):
        self.name=name
        self.args=args
        self.calls={}
        self.commons={}
        self.includes={}

    def __setitem__(self, name, args):
        tmp=FortCall(name, args)
        if not self.calls.has_key(name):
            self.calls[name]=[]
        self.calls[name].append(tmp)

    def get_calls(self):
        tmp=[]
        for i in self.calls.keys():
            for j in self.calls[i]:
                tmp.append(j)
        return tmp

    def filter_includes(self, list):
        for i in list:
            if self.includes.has_key(i):
                del self.includes[i]

    def add_common_block(self, comn):
        self.commons[comn[0]]=comn[1]

    def add_include(self, incl):
        self.includes[incl]=None

    def get_commons(self):
        return self.commons

    def get_includes(self):
        return self.includes

    def has_key(self, key):
        return self.calls.has_key(key)

    def __getitem__(self, name):
        return self.calls[name]

    def __str__(self):
        s=self.name+'('
        for i in self.args:
            s=s+i+","
        if s[-1] != '(':
            s=s[:-2]+')\n'
        else:
            s=s+')\n'
        s=s+'-'*10+'\n'
        for i in self.commons:
            s=s+'/'+i+'/'+'\n'
        for i in self.includes:
            s=s+'<'+i+'>'+'\n'
        for i in self.calls.keys():
            for j in self.calls[i]:
                s=s+j.__str__()+'\n'
        return s

    def dotty(self):
        for i in self.commons:
            print "\"%s\" -> \"/%s/\";" % (self.name, i)
        for i in self.includes:
            print "\"%s\" -> \"<%s>\";" % (self.name, i)

class FortCall(Common):
    def __init__(self, name, args):
        self.name=name
        self.args=args

    def __str__(self):
        s=self.name+'('
        for i in self.args:
            s=s+i+","
        if s[-1] != '(':
            s=s[:-2]+')'
        else:
            s=s+')'
        return s

def main():
    try:
        opts,args=getopt.getopt(sys.argv[1:], "hd:p")
    except:
        usage()
#    if len(opts) < 1: #or len(args) != 2:
#        usage()
    dbfile=None
#    for o,a in opts:
#        if o == '-h':
#            usage()
#        elif o == '-d':
#            dbfile=a
#        elif o == '-p':
#            peek=1
#        else:
#            usage()

#    print """
#    digraph prof {
#    ratio = fill;
#    size="25,10";
#    page="8.5,11";
#    """
    for i in args:
        ffile=parse_file(i)
        print ffile
#        ffile.dotty()

#    print "}"


if __name__ == '__main__':
    main()
