#!/usr/bin/env python

from argparse import ArgumentParser, FileType, Namespace
from ast import AST, Name, iter_fields, parse, walk, stmt, literal_eval
from astunparse import unparse
from collections import defaultdict
from copy import deepcopy
from typing import Optional, TextIO
import sys
import ast

from flor.hlast.gumtree import GumTree, Mapping, python

# https://github.com/PyCQA/pylint/issues/3882
# pylint: disable=unsubscriptable-object


def add_arguments(parser: ArgumentParser):
    parser.add_argument("lineno", type=int)
    parser.add_argument("source", type=FileType("r"))
    parser.add_argument("target", type=FileType("r+"))
    parser.add_argument("--out", type=FileType("w"), default=sys.stdout)
    parser.add_argument("--minor", type=int, default=sys.version_info[1])
    parser.add_argument("--gumtree", type=literal_eval, default="{}")
    return parser


def propagate(args: Namespace):
    tree, target = [parse(f.read()) for f in (args.source, args.target)]
    replicate(tree, find(tree, lineno=args.lineno), target, **args.gumtree)  # type: ignore
    print(unparse(target), file=args.out)


def replicate(tree: AST, node: stmt, target: AST, **kwargs):
    """
    First we do code-block alignment using the GumTree
    algorithm from Falleri et al.
    """
    adapter = python.Adapter(tree, target)
    mapping = GumTree(adapter, **kwargs).mapping(tree, target)
    # asserting `tree` is the root of `node` in the `adapter`
    assert tree == adapter.root(node) and isinstance(node, stmt)

    """
    Then we insert the back-propagated statement into the target block
    QUERY:
        Is the back-propagation always intra-block, meaning from
        same block in version v to same block in version ancestor(v)


    It's working. It's not off by one, it's finding an 
    adjacent injection site.

    The contextual copy ignores content of target
    """
    block, index = find_insert_loc(adapter, node, mapping)
    if node in mapping:
        lev = LoggedExpVisitor()
        lev.visit(node)
        new = block.pop(index)  # type: ignore
        pnv = PairNodeVisitor(lev.name)
        new = pnv.visit(node, new)
        # new = make_contextual_mutate(node, target)
    else:
        new = make_contextual_copy(adapter, node, mapping)
    block.insert(index, new)  # type: ignore
    # block.pop(index - 2)


class PairNodeVisitor(ast.NodeTransformer):
    def __init__(self, name):
        super().__init__()
        self.name = name

    def make_wrapper(self, child):
        if isinstance(child, AST):
            return (
                ast.parse(f"flor.log('{self.name}',{unparse(child).strip()})")
                .body[0]
                .value  # type: ignore
            )
        elif isinstance(child, (list, tuple)):
            return (
                ast.parse(
                    f"flor.log('{self.name}',{[unparse(c).strip() for c in child]})"
                )
                .body[0]
                .value  # type:ignore
            )
        else:
            raise NotImplementedError

    def equals(self, node1: AST, node2: AST):
        return node1.__class__ == node2.__class__ and all(
            [type(getattr(node1, a)) == type(getattr(node2, a)) for a in node1._fields]
        )

    def visit(self, node1: AST, node2: AST):
        """Visit a node."""
        if not self.equals(node1, node2):

            field = None

            for f in node1._fields:
                v = getattr(node1, f)
                s = unparse(v).strip() if isinstance(v, AST) else str(v)
                if "flor" in s:
                    field = f
                    break
            ...

            child = getattr(node2, field)
            logging_child = self.make_wrapper(child)
            setattr(node2, field, logging_child)
            return node2
        return self.generic_visit(node1, node2)

    def generic_visit(self, node1, node2):
        for (fld1, old_val1), (fld2, old_val2) in zip(
            iter_fields(node1), iter_fields(node2)
        ):
            if isinstance(old_val1, list):
                assert isinstance(old_val2, list)
                new_values = []
                for val1, val2 in zip(old_val1, old_val2):
                    if isinstance(val1, AST):
                        assert isinstance(val2, AST)
                        val2 = self.visit(val1, val2)
                        if val2 is None:
                            continue
                        elif not isinstance(val2, AST):
                            new_values.extend(val2)
                            continue
                    new_values.append(val2)
                old_val2[:] = new_values
            elif isinstance(old_val1, AST):
                assert isinstance(old_val2, AST)
                new_node = self.visit(old_val1, old_val2)
                if new_node is None:
                    delattr(node1, fld1)
                    delattr(node2, fld2)
                else:
                    setattr(node2, fld2, new_node)
        return node2


class LoggedExpVisitor(ast.NodeVisitor):
    def __init__(self):
        super().__init__()
        self.name: Optional[str] = None

    def visit_Call(self, node: ast.Call):
        pred = (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "flor"
            and node.func.attr == "log"
        )
        if not pred:
            return self.generic_visit(node)
        if len(node.args) == 2 and isinstance(node.args[0], ast.Constant):
            self.name = str(node.args[0].value)
        else:
            raise


def find_insert_loc(adapter, node, mapping):
    parent = adapter.parent(node)

    context = None
    for sibling in adapter.children(parent):
        if id(sibling) == id(node):
            break
        if sibling in mapping:
            context = sibling

    if context is not None:
        ref = mapping[context]
        block = adapter.parent(ref)
        index = 1 + block.index(ref)
    elif parent in mapping:
        block = mapping[parent]
        index = 0
    else:
        exit("Unable to map context!")

    return block, index


def make_contextual_copy(adapter, node, mapping):
    renames = defaultdict(lambda: defaultdict(int))
    for source, target in mapping.items():
        if isinstance(source, Name) and not adapter.contains(source, node):
            renames[source.id][target.id] += 1

    new = deepcopy(node)
    for n in walk(new):
        if isinstance(n, Name) and n.id in renames:
            n.id = max(renames[n.id], key=renames[n.id].get)  # type: ignore
    return new


def find(t: AST, *, lineno: int):
    adapter = python.Adapter(t)  # FIXME: odd dependency
    res = None
    for n in adapter.postorder(t):
        if getattr(n, "lineno", lineno) == lineno and isinstance(n, stmt):
            res = n
    return res


if __name__ == "__main__":
    propagate(add_arguments(ArgumentParser()).parse_args(sys.argv[1:]))
