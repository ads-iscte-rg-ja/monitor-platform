package main

import (
	"encoding/csv"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"path/filepath"
	"strconv"
)

type functionMetrics struct {
	pkg, file, name string
	line, lines     int
	cyclomatic      int
}

// runFunctions escreve uma linha por função ou método declarado.
func runFunctions(dir string, out io.Writer) error {
	pkgs, err := listPackages(dir)
	if err != nil {
		return err
	}
	var rows []functionMetrics
	for _, p := range pkgs {
		pkgRows, err := packageFunctions(p, shortName(p.Module.Path, p.ImportPath))
		if err != nil {
			return err
		}
		rows = append(rows, pkgRows...)
	}
	w := csv.NewWriter(out)
	_ = w.Write([]string{"package", "file", "line", "function", "lines", "cyclomatic"})
	for _, f := range rows {
		_ = w.Write([]string{f.pkg, f.file, strconv.Itoa(f.line), f.name, strconv.Itoa(f.lines), strconv.Itoa(f.cyclomatic)})
	}
	w.Flush()
	return w.Error()
}

func packageFunctions(p goPackage, pkg string) ([]functionMetrics, error) {
	fset := token.NewFileSet()
	var rows []functionMetrics
	for _, name := range p.GoFiles {
		f, err := parser.ParseFile(fset, filepath.Join(p.Dir, name), nil, parser.SkipObjectResolution)
		if err != nil {
			return nil, err
		}
		for _, decl := range f.Decls {
			fn, ok := decl.(*ast.FuncDecl)
			if !ok || fn.Body == nil {
				continue
			}
			start, end := fset.Position(fn.Pos()), fset.Position(fn.End())
			rows = append(rows, functionMetrics{
				pkg:        pkg,
				file:       filepath.Join(pkg, name),
				name:       funcName(fn),
				line:       start.Line,
				lines:      end.Line - start.Line + 1,
				cyclomatic: cyclomatic(fn),
			})
		}
	}
	return rows, nil
}

func funcName(fn *ast.FuncDecl) string {
	if fn.Recv == nil || len(fn.Recv.List) == 0 {
		return fn.Name.Name
	}
	t := fn.Recv.List[0].Type
	if star, ok := t.(*ast.StarExpr); ok {
		t = star.X
	}
	if idx, ok := t.(*ast.IndexExpr); ok { // recetor genérico
		t = idx.X
	}
	if id, ok := t.(*ast.Ident); ok {
		return "(" + id.Name + ")." + fn.Name.Name
	}
	return fn.Name.Name
}

// cyclomatic segue a contagem do gocyclo: 1 + if, for, range, case e
// comunicação não omissos, && e ||. As funções anónimas contam para a
// função que as contém.
func cyclomatic(fn *ast.FuncDecl) int {
	c := 1
	ast.Inspect(fn.Body, func(n ast.Node) bool {
		switch n := n.(type) {
		case *ast.IfStmt, *ast.ForStmt, *ast.RangeStmt:
			c++
		case *ast.CaseClause:
			if n.List != nil {
				c++
			}
		case *ast.CommClause:
			if n.Comm != nil {
				c++
			}
		case *ast.BinaryExpr:
			if n.Op == token.LAND || n.Op == token.LOR {
				c++
			}
		}
		return true
	})
	return c
}
