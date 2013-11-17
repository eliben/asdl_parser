#-------------------------------------------------------------------------------
# Parser for ASDL [1] definition files. Reads in an ASDL description and parses
# it into an AST that describes it.
#
# The EBNF we're parsing here: Figure 1 of the paper [1]. Extended to support
# modules and attributes after a product. Words starting with Capital letters
# are terminals. Others are non-terminals. Id is either TokenId or
# ConstructorId.
#
# module        ::= Id Id "{" [definitions] "}"
# definitions   ::= { TypeId "=" type }
# type          ::= product | sum
# product       ::= fields [attributes fields]
# fields        ::= "(" { field, "," } field ")"
# field         ::= TypeId ["?" | "*"] [Id]
# sum           ::= constructor { "|" constructor } [attributes fields]
# constructor   ::= ConstructorId [fields]
#
# [1] "The Zephyr Abstract Syntax Description Language" by Wang, et. al. See
#     http://asdl.sourceforge.net/
#-------------------------------------------------------------------------------
from collections import namedtuple
from enum import Enum
import re

__all__ = [
    'builtin_types', 'parse', 'AST', 'Module', 'Type', 'Constructor',
    'Field', 'Sum', 'Product', 'VisitorBase', 'Check', 'check']

# The following classes define nodes into which the ASDL description is parsed.
# Note: this is a "meta-AST". ASDL files (such as Python.asdl) describe the AST
# structure used by a programming language. But ASDL files themselves need to be
# parsed. This module parses ASDL files and uses a simple AST to represent them.

builtin_types = set(
    ['identifier', 'string', 'bytes', 'int', 'object', 'singleton'])

class AST: pass # a marker class

class Module(AST):
    def __init__(self, name, dfns):
        self.name = name
        self.dfns = dfns
        self.types = {type.name: type.value for type in dfns}

    def __repr__(self):
        return 'Module({0.name}, {0.dfns})'.format(self)

class Type(AST):
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def __repr__(self):
        return 'Type({0.name}, {0.value})'.format(self)

class Constructor(AST):
    def __init__(self, name, fields=None):
        self.name = name
        self.fields = fields or []

    def __repr__(self):
        return 'Constructor({0.name}, {0.fields})'.format(self)

class Field(AST):
    def __init__(self, type, name=None, seq=False, opt=False):
        self.type = type
        self.name = name
        self.seq = seq
        self.opt = opt

    def __repr__(self):
        if self.seq:
            extra = ", seq=True"
        elif self.opt:
            extra = ", opt=True"
        else:
            extra = ""
        if self.name is None:
            return 'Field({0.type}{1})'.format(self, extra)
        else:
            return 'Field({0.type}, {0.name}{1})'.format(self, extra)

class Sum(AST):
    def __init__(self, types, attributes=None):
        self.types = types
        self.attributes = attributes or []

    def __repr__(self):
        if self.attributes:
            return 'Sum({0.types}, {0.attributes})'.format(self)
        else:
            return 'Sum({0.types})'.format(self)

class Product(AST):
    def __init__(self, fields, attributes=None):
        self.fields = fields
        self.attributes = attributes or []

    def __repr__(self):
        if self.attributes:
            return 'Product({0.fields}, {0.attributes})'.format(self)
        else:
            return 'Product({0.fields})'.format(self)

# A generic visitor for the meta-AST that describes ASDL. This can be used by
# emitters. We also define a Check visitor that makes sure the parsed ASDL is
# well-formed.

class VisitorBase:
    """Generic tree visitor for ASTs."""
    def __init__(self):
        self.cache = {}

    def visit(self, obj, *args):
        klass = obj.__class__
        meth = self.cache.get(klass)
        if meth is None:
            methname = "visit" + klass.__name__
            meth = getattr(self, methname, None)
            self.cache[klass] = meth
        if meth:
            try:
                meth(obj, *args)
            except Exception as e:
                print("Error visiting %r: %s" % (obj, e))
                raise

class Check(VisitorBase):
    """A visitor that checks a parsed ASDL tree for correctness.

    Errors are printed and accumulated.
    """
    def __init__(self):
        super().__init__()
        self.cons = {}
        self.errors = 0
        self.types = {}

    def visitModule(self, mod):
        for dfn in mod.dfns:
            self.visit(dfn)

    def visitType(self, type):
        self.visit(type.value, str(type.name))

    def visitSum(self, sum, name):
        for t in sum.types:
            self.visit(t, name)

    def visitConstructor(self, cons, name):
        key = str(cons.name)
        conflict = self.cons.get(key)
        if conflict is None:
            self.cons[key] = name
        else:
            print('Redefinition of constructor' + key)
            print('Defined in {} and {}'.format(conflict, name))
            self.errors += 1
        for f in cons.fields:
            self.visit(f, key)

    def visitField(self, field, name):
        key = str(field.type)
        l = self.types.setdefault(key, [])
        l.append(name)

    def visitProduct(self, prod, name):
        for f in prod.fields:
            self.visit(f, name)

def check(mod):
    """Check the parsed ASDL tree for correctness.

    Return True if success. For failure, the errors are printed out and False
    is returned.
    """
    v = Check()
    v.visit(mod)

    for t in v.types:
        if t not in mod.types and not t in builtin_types:
            v.errors += 1
            uses = ", ".join(v.types[t])
            print('Undefined type {}, used in {}'.format(t, uses))
    return not v.errors

# The ASDL parser itself comes next. The only interesting external interface
# here is the top-level parse function.

def parse(filename):
    """Parse ASDL from the given file and return a Module node describing it."""
    with open(filename) as f:
        parser = ASDLParser()
        return parser.parse(f.read())

# Types for describing tokens in an ASDL specification.
TokenKind = Enum('TokenKind', '''ConstructorId TypeId Equals Question Pipe
                                 LParen RParen Comma Asterisk LBrace RBrace''')

Token = namedtuple('Token', 'kind value lineno')

class ASDLSyntaxError(Exception):
    def __init__(self, msg, lineno=None):
        self.msg = msg
        self.lineno = lineno or '<unknown>'

    def __str__(self):
        return 'Syntax error on line {0.lineno}: {0.msg}'.format(self)

def tokenize_asdl(buf):
    """Tokenize the given buffer. Yield Token objects."""
    buflen = len(buf)
    pos = 0
    lineno = 1

    while pos < buflen:
        m = tokenize_asdl._re_skip_whitespace.search(buf, pos)
        if not m: return
        lineno += buf.count('\n', pos, m.start())
        pos = m.start()
        c = buf[pos]
        if c.isalpha():
            # Some kind of identifier
            m = tokenize_asdl._re_nonword.search(buf, pos + 1)
            end = m.end() - 1 if m else buflen
            id = buf[pos:end]
            if c.isupper():
                yield Token(TokenKind.ConstructorId, id, lineno)
            else:
                yield Token(TokenKind.TypeId, id, lineno)
            pos = end
        elif c == '-':
            # Potential comment, if followed by another '-'
            if pos < buflen - 1 and buf[pos + 1] == '-':
                pos = buf.find('\n', pos + 1)
                if pos < 0: pos = buflen
                continue
            else:
                raise ASDLSyntaxError('Invalid operator ' + c, lineno)
        else:
            # Operators
            op_kind = tokenize_asdl._operator_table.get(c, None)
            if op_kind:
                yield Token(op_kind, c, lineno)
            else:
                raise ASDLSyntaxError('Invalid operator %s' % c, lineno)
            pos += 1

# Immutable helper objects for tokenize_asdl.
tokenize_asdl._re_skip_whitespace = re.compile(r'\S')
tokenize_asdl._re_nonword = re.compile(r'\W')
tokenize_asdl._operator_table = {
    '=': TokenKind.Equals,      ',': TokenKind.Comma,   '?': TokenKind.Question,
    '|': TokenKind.Pipe,        '(': TokenKind.LParen,  ')': TokenKind.RParen,
    '*': TokenKind.Asterisk,    '{': TokenKind.LBrace,  '}': TokenKind.RBrace}

class ASDLParser:
    """Parser for ASDL files.

    Create, then call the parse method on a buffer containing ASDL.
    This is a simple recursive descent parser that uses tokenize_asdl for the
    lexing.
    """
    def __init__(self):
        self._tokenizer = None
        self.cur_token = None

    def parse(self, buf):
        """Parse the ASDL in the buffer and return an AST with a Module root.
        """
        self._tokenizer = tokenize_asdl(buf)
        self._advance()
        return self._parse_module()

    def _parse_module(self):
        if self._at_keyword('module'):
            self._advance()
        else:
            raise ASDLSyntaxError(
                'Expected "module" (found {})'.format(self.cur_token.value),
                self.cur_token.lineno)
        name = self._match(self._id_kinds)
        self._match(TokenKind.LBrace)
        defs = self._parse_definitions()
        self._match(TokenKind.RBrace)
        return Module(name, defs)

    def _parse_definitions(self):
        defs = []
        while self.cur_token.kind == TokenKind.TypeId:
            typename = self._advance()
            self._match(TokenKind.Equals)
            type = self._parse_type()
            defs.append(Type(typename, type))
        return defs

    def _parse_type(self):
        if self.cur_token.kind == TokenKind.LParen:
            # If we see a (, it's a product
            return self._parse_product()
        else:
            # Otherwise it's a sum. Look for ConstructorId
            sumlist = [Constructor(self._match(TokenKind.ConstructorId),
                                   self._parse_optional_fields())]
            while self.cur_token.kind  == TokenKind.Pipe:
                # More constructors
                self._advance()
                sumlist.append(Constructor(
                                self._match(TokenKind.ConstructorId),
                                self._parse_optional_fields()))
            return Sum(sumlist, self._parse_optional_attributes())

    def _parse_product(self):
        return Product(self._parse_fields(), self._parse_optional_attributes())

    def _parse_fields(self):
        fields = []
        self._match(TokenKind.LParen)
        while self.cur_token.kind == TokenKind.TypeId:
            typename = self._advance()
            is_seq, is_opt = self._parse_optional_field_quantifier()
            id = (self._advance() if self.cur_token.kind in self._id_kinds
                                  else None)
            fields.append(Field(typename, id, seq=is_seq, opt=is_opt))
            if self.cur_token.kind == TokenKind.RParen:
                break
            elif self.cur_token.kind == TokenKind.Comma:
                self._advance()
        self._match(TokenKind.RParen)
        return fields

    def _parse_optional_fields(self):
        if self.cur_token.kind == TokenKind.LParen:
            return self._parse_fields()
        else:
            return None

    def _parse_optional_attributes(self):
        if self._at_keyword('attributes'):
            self._advance()
            return self._parse_fields()
        else:
            return None

    def _parse_optional_field_quantifier(self):
        is_seq, is_opt = False, False
        if self.cur_token.kind == TokenKind.Asterisk:
            is_seq = True
            self._advance()
        elif self.cur_token.kind == TokenKind.Question:
            is_opt = True
            self._advance()
        return is_seq, is_opt

    def _advance(self):
        """ Return the value of the current token and read the next one into
            self.cur_token.
        """
        cur_val = None if self.cur_token is None else self.cur_token.value
        try:
            self.cur_token = next(self._tokenizer)
        except StopIteration:
            self.cur_token = None
        return cur_val

    _id_kinds = (TokenKind.ConstructorId, TokenKind.TypeId)

    def _match(self, kind):
        """The 'match' primitive of RD parsers.

        * Verifies that the current token is of the given kind (kind can
          be a tuple, in which the kind must match one of its members).
        * Returns the value of the current token
        * Reads in the next token
        """
        if (isinstance(kind, tuple) and self.cur_token.kind in kind or
            self.cur_token.kind == kind
            ):
            value = self.cur_token.value
            self._advance()
            return value
        else:
            raise ASDLSyntaxError(
                'Unmatched {} (found {})'.format(kind, self.cur_token.kind),
                self.cur_token.lineno)

    def _at_keyword(self, keyword):
        return (self.cur_token.kind == TokenKind.TypeId and
                self.cur_token.value == keyword)
