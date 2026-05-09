import ast
import re
from pathlib import Path

from app.core.config import settings

# SEND 源码索引服务
class SendCodeIndexService:
    """
    SEND 转换源码结构化索引服务。
    该服务按需扫描 domain_lib 下的 Python 文件，把字段赋值和 DataFrame 字段依赖整理成可精确查询的数据。
    """
    _index_cache: dict | None = None

    @classmethod
    def clear_cache(cls):
        """
        清空源码索引缓存，便于代码更新后重新扫描。
        """
        cls._index_cache = None

    @classmethod
    def get_source_root(cls) -> Path:
        """
        返回 SEND 转换源码目录。
        """
        return Path(settings.send_code_root)

    @classmethod
    def safe_unparse(cls, node: ast.AST) -> str:
        """
        将 AST 节点转成单行代码表达式。
        """
        try:
            return " ".join(ast.unparse(node).split())
        except Exception:
            return ""

    @classmethod
    def direct_string_slice_values(cls, node: ast.AST) -> list[str]:
        """
        提取 DataFrame 下标里的直接字符串字段名。
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, (ast.List, ast.Tuple)):
            return [
                item.value for item in node.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
        return []

    @classmethod
    def extract_assigned_dataframe_field(cls, target: ast.AST) -> str | None:
        """
        从 df.loc[..., 'FIELD'] = value 中提取被赋值字段名。
        """
        if not isinstance(target, ast.Subscript):
            return None
        value_text = cls.safe_unparse(target.value)
        if not (value_text.endswith(".loc") or value_text.endswith(".iloc") or value_text.endswith(".at")):
            return None
        candidates = list(target.slice.elts) if isinstance(target.slice, ast.Tuple) else [target.slice]
        for candidate in reversed(candidates):
            values = cls.direct_string_slice_values(candidate)
            if values:
                return values[-1]
        return None

    @classmethod
    def infer_domain_from_dataframe(cls, dataframe_name: str) -> str | None:
        """
        根据 df_ex / df_pc 这类变量名推断对应 SEND 域。
        """
        suffix = dataframe_name.removeprefix("df_").upper()
        known_domains = {
            "BG", "BW", "CL", "CV", "DM", "DS", "EG", "EX", "FW", "GV",
            "LB", "MA", "MI", "OM", "PC", "PP", "RE", "RELREC", "SE",
            "TA", "TE", "TS", "TX", "VS"
        }
        return suffix if suffix in known_domains else None

    @classmethod
    def line_window(cls, lines: list[str], lineno: int, radius: int = 4) -> str:
        """
        返回字段赋值附近的源代码片段。
        """
        start = max(1, lineno - radius)
        end = min(len(lines), lineno + radius)
        return "\n".join(f"{idx}: {lines[idx - 1].rstrip()}" for idx in range(start, end + 1))

    @classmethod
    def extract_dependencies(cls, expr: str) -> list[str]:
        """
        从表达式中提取主要依赖对象。
        """
        deps = []
        patterns = [
            r"\b(df_[A-Za-z0-9_]+)\b",
            r"\bitem\[['\"]([^'\"]+)['\"]\]",
            r"\b(df_[A-Za-z0-9_]+)\[['\"]([^'\"]+)['\"]\]",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, expr):
                groups = [item for item in match.groups() if item]
                dep = ".".join(groups)
                if dep not in deps:
                    deps.append(dep)
        return deps

    @classmethod
    def collect_functions(cls, tree: ast.AST) -> list[dict]:
        """
        提取函数签名，用于域级逻辑摘要。
        """
        functions = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            functions.append({
                "name": node.name,
                "line": node.lineno,
                "args": [arg.arg for arg in node.args.args],
            })
        return sorted(functions, key=lambda item: item["line"])

    @classmethod
    def collect_local_assignments_and_returns(cls, tree: ast.AST, lines: list[str]) -> tuple[dict, dict]:
        """
        收集函数内本地变量赋值和 return 分支，用于字段级深度追踪。
        """
        local_assignments: dict[str, list[dict]] = {}
        function_returns: dict[str, list[dict]] = {}

        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if isinstance(node, ast.Assign):
                    expr = cls.safe_unparse(node.value)
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            local_assignments.setdefault(target.id, []).append({
                                "function": function.name,
                                "line": node.lineno,
                                "expression": expr,
                                "dependencies": cls.extract_dependencies(expr),
                                "snippet": cls.line_window(lines, node.lineno),
                            })
                elif isinstance(node, ast.Return):
                    expr = cls.safe_unparse(node.value)
                    item = {
                        "function": function.name,
                        "line": node.lineno,
                        "expression": expr,
                        "dict_items": {},
                        "snippet": cls.line_window(lines, node.lineno),
                    }
                    if isinstance(node.value, ast.Dict):
                        for key, value in zip(node.value.keys, node.value.values):
                            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                item["dict_items"][key.value] = cls.safe_unparse(value)
                    function_returns.setdefault(function.name, []).append(item)

        return local_assignments, function_returns

    @classmethod
    def collect_reachable_function_ranges(cls, tree: ast.AST) -> list[tuple[int, int]]:
        """
        从 convert_* 入口出发，收集可达函数的源码行范围。
        域级摘要只使用这些范围，避免未调用的历史辅助函数污染主逻辑。
        """
        functions = {
            node.name: node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        starts = [name for name in functions if name.startswith("convert_")]
        if not starts:
            starts = [name for name in functions if name.endswith("_csv")]

        reachable = set()
        pending = list(starts)
        while pending:
            name = pending.pop()
            if name in reachable or name not in functions:
                continue
            reachable.add(name)
            for node in ast.walk(functions[name]):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    callee = node.func.id
                    if callee in functions and callee not in reachable:
                        pending.append(callee)

        ranges = []
        for name in reachable:
            node = functions[name]
            end = getattr(node, "end_lineno", node.lineno)
            ranges.append((node.lineno, end))
        return sorted(ranges)

    @classmethod
    def line_in_ranges(cls, line: int, ranges: list[tuple[int, int]]) -> bool:
        """
        判断行号是否落在可达函数范围内。
        """
        if not ranges:
            return True
        return any(start <= line <= end for start, end in ranges)

    @classmethod
    def collect_list_assignments(cls, tree: ast.AST) -> dict[str, list[str]]:
        """
        提取 columns_list 这类字段模板。
        """
        result = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                continue
            values = [
                item.value for item in node.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            if not values:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith("columns_list"):
                    result[target.id] = values
        return result

    @classmethod
    def collect_domain_operations(
        cls,
        tree: ast.AST,
        lines: list[str],
        domain: str,
        ranges: list[tuple[int, int]] | None = None
    ) -> dict[str, list[dict]]:
        """
        抽取排序、合并、清理、输出、时间点等通用操作。
        这里只做可解释的静态证据抽取，不尝试把所有业务语义硬编码成自然语言。
        """
        groups = {
            "preprocessing": [],
            "time_point": [],
            "baseline": [],
            "cleanup_output": [],
        }
        time_tokens = ("DTC", "DY", "TPT", "ELTM", "RFTDTC", "NOMDY", "NOMLBL", "VISIT")
        baseline_tokens = ("BLFL", "baseline", "Predose", "PREDOSE")
        output_tokens = ("xport.Dataset", "upload_samba_xpt_file", ".xpt", "Library")
        cleanup_tokens = ("sort_values", "drop", "dropna", "reset_index", "astype", "range(1, len")
        preprocess_tokens = ("concat", "merge", "pivot", "rename", "fillna", "sort_values", "dropna", "reset_index")

        for idx, line in enumerate(lines, start=1):
            if ranges and not cls.line_in_ranges(idx, ranges):
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            upper = stripped.upper()
            item = {"line": idx, "code": stripped}
            if any(token.upper() in upper for token in time_tokens):
                groups["time_point"].append(item)
            if any(token.upper() in upper for token in baseline_tokens):
                groups["baseline"].append(item)
            if any(token in stripped for token in output_tokens):
                groups["cleanup_output"].append(item)
            elif any(token in stripped for token in cleanup_tokens):
                groups["cleanup_output"].append(item)
            if any(token in stripped for token in preprocess_tokens):
                groups["preprocessing"].append(item)

        return {
            key: values[:12]
            for key, values in groups.items()
            if values
        }

    @classmethod
    def filter_fields_by_ranges(cls, fields: dict[str, list[dict]], ranges: list[tuple[int, int]]) -> dict[str, list[dict]]:
        if not ranges:
            return fields
        result = {}
        for field, entries in fields.items():
            kept = [entry for entry in entries if cls.line_in_ranges(int(entry.get("line") or 0), ranges)]
            if kept:
                result[field] = kept
        return result

    @classmethod
    def filter_dependencies_by_ranges(
        cls,
        dependencies: dict[str, dict[str, list[dict]]],
        ranges: list[tuple[int, int]]
    ) -> dict[str, dict[str, list[dict]]]:
        if not ranges:
            return dependencies
        result = {}
        for used_domain, columns in dependencies.items():
            for field, entries in columns.items():
                kept = [entry for entry in entries if cls.line_in_ranges(int(entry.get("line") or 0), ranges)]
                if kept:
                    result.setdefault(used_domain, {})[field] = kept
        return result

    @classmethod
    def build_domain_logic_payload(cls, file_index: dict) -> dict:
        """
        根据源码索引构造所有域共用的域级转换逻辑。
        """
        domain = file_index["domain"]
        fields = file_index.get("fields", {})
        dependencies = file_index.get("dependencies", {})
        functions = file_index.get("functions", [])
        columns = file_index.get("columns", {})
        operations = file_index.get("operations", {})

        convert_functions = [item for item in functions if item["name"].startswith("convert_")]
        worker_functions = [
            item for item in functions
            if item["name"].endswith("_csv") or item["name"].startswith(("get_", "parse_", "resolve_", "format_"))
        ][:8]

        input_sources = []
        function_args = []
        for item in convert_functions + worker_functions:
            for arg in item.get("args") or []:
                if arg.startswith("df_") and arg not in function_args:
                    function_args.append(arg)
        if function_args:
            input_sources.append("函数参数中的输入表：" + ", ".join(function_args))

        internal_dependency_keys = {"df_res", "df_res_sort", "df_group", "df_group_phase"}
        for used_domain, columns_by_name in sorted(dependencies.items()):
            if used_domain in internal_dependency_keys:
                continue
            column_names = sorted(columns_by_name.keys())
            label = f"{used_domain} 域" if re.fullmatch(r"[A-Z]{2,}", used_domain) else used_domain
            input_sources.append(f"{label} 输入字段：{', '.join(column_names[:18])}")

        function_names = [f"{item['name']}() 行 {item['line']}" for item in convert_functions + worker_functions[:5]]
        core_logic = []
        if function_names:
            core_logic.append("入口/辅助函数：" + "；".join(function_names))
        core_logic.append(f"源码中识别到 {len(fields)} 个 {domain} 输出字段的赋值或结果字典写入。")

        key_field_order = [
            "USUBJID", f"{domain}TESTCD", f"{domain}TEST", f"{domain}ORRES", f"{domain}STRESC",
            f"{domain}STRESN", f"{domain}STRESU", f"{domain}DTC", f"{domain}DY", f"{domain}TPT",
            f"{domain}ELTM", f"{domain}RFTDTC", f"{domain}BLFL", f"{domain}SEQ"
        ]

        def meaningful_entries(entries: list[dict]) -> list[dict]:
            lows = []
            highs = []
            for entry in sorted(entries or [], key=lambda value: int(value.get("line") or 0)):
                expr = str(entry.get("expression") or "").strip()
                field = str(entry.get("field") or "").strip()
                if expr == field:
                    continue
                if expr in {"''", '""', "None", "np.nan", "nan"}:
                    lows.append(entry)
                else:
                    highs.append(entry)
            return highs or lows

        examples_by_field: dict[str, list[str]] = {}
        for field in key_field_order:
            entries = fields.get(field) or []
            if entries:
                for entry in meaningful_entries(entries)[:4]:
                    examples_by_field.setdefault(field, []).append(f"{field}: 行 {entry.get('line')}，{entry.get('expression')}")
        examples = []
        for field in key_field_order:
            items = examples_by_field.get(field) or []
            if field.endswith("ORRES"):
                examples.extend(items[:3])
            elif field.endswith(("STRESC", "STRESN", "STRESU")):
                examples.extend(items[:2])
            else:
                examples.extend(items[:1])
        if not examples:
            for field, entries in sorted(fields.items())[:8]:
                for entry in meaningful_entries(entries)[:2]:
                    examples.append(f"{field}: 行 {entry.get('line')}，{entry.get('expression')}")
        if examples:
            core_logic.append("关键字段赋值示例：" + "；".join(examples[:14]))

        preprocessing = operations.get("preprocessing") or []
        if preprocessing:
            core_logic.append(
                "数据整理步骤：" + "；".join(f"行 {item['line']} {item['code']}" for item in preprocessing[:5])
            )

        time_point_logic = []
        for field in key_field_order:
            if any(token in field for token in ("DTC", "DY", "TPT", "ELTM", "RFTDTC", "NOMDY", "BLFL")):
                entries = fields.get(field) or []
                for entry in meaningful_entries(entries)[:4]:
                    time_point_logic.append(f"{field}: 行 {entry.get('line')}，{entry.get('expression')}")
        for item in (operations.get("time_point") or [])[:8]:
            line_text = f"行 {item['line']}，{item['code']}"
            if line_text not in time_point_logic:
                time_point_logic.append(line_text)
        for item in (operations.get("baseline") or [])[:5]:
            line_text = f"基线/给药前处理：行 {item['line']}，{item['code']}"
            if line_text not in time_point_logic:
                time_point_logic.append(line_text)

        dependency_lines = []
        for used_domain, columns_by_name in sorted(dependencies.items()):
            if used_domain in internal_dependency_keys:
                continue
            column_names = sorted(columns_by_name.keys())
            label = f"{used_domain} 域" if re.fullmatch(r"[A-Z]{2,}", used_domain) else used_domain
            dependency_lines.append(f"读取 {label} 字段：{', '.join(column_names[:20])}")

        output_fields = []
        for values in columns.values():
            for value in values:
                if value not in output_fields:
                    output_fields.append(value)
        if not output_fields:
            output_fields = sorted(fields.keys())

        outputs = []
        if output_fields:
            outputs.append("输出字段：" + ", ".join(output_fields[:28]))
        for item in (operations.get("cleanup_output") or [])[:8]:
            outputs.append(f"清理/排序/输出代码：行 {item['line']}，{item['code']}")

        return {
            "domain_role": f"{domain} 域用于生成 SEND {domain}.xpt 数据集；以下摘要来自源码静态索引，不是手写域特例。",
            "input_sources": input_sources or None,
            "core_logic": core_logic or None,
            "time_point_logic": time_point_logic or None,
            "dependencies": dependency_lines or None,
            "outputs": outputs or None,
        }

    @classmethod
    def scan_file(cls, path: Path) -> dict:
        """
        扫描单个域代码文件。
        """
        source = path.read_text(encoding="utf-8-sig")
        lines = source.splitlines()
        tree = ast.parse(source)
        domain = path.stem.upper()
        field_pattern = re.compile(rf"^({domain}|STUDYID|DOMAIN|USUBJID|IDVAR|IDVARVAL|QNAM|QLABEL|QVAL|QORIG)[A-Z0-9_]*$")
        fields: dict[str, list[dict]] = {}
        dataframe_refs: dict[str, dict[str, list[dict]]] = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                expr = cls.safe_unparse(node.value)
                for target in node.targets:
                    field = None
                    if isinstance(target, ast.Name) and field_pattern.match(target.id):
                        field = target.id
                    elif isinstance(target, ast.Subscript):
                        assigned_field = cls.extract_assigned_dataframe_field(target)
                        if assigned_field and field_pattern.match(assigned_field):
                            field = assigned_field
                    if field:
                        fields.setdefault(field, []).append({
                            "domain": domain,
                            "field": field,
                            "file": str(path),
                            "line": node.lineno,
                            "expression": expr,
                            "dependencies": cls.extract_dependencies(expr),
                            "snippet": cls.line_window(lines, node.lineno),
                        })

            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                        continue
                    field = key.value
                    if field_pattern.match(field):
                        expr = cls.safe_unparse(value)
                        fields.setdefault(field, []).append({
                            "domain": domain,
                            "field": field,
                            "file": str(path),
                            "line": getattr(key, "lineno", getattr(node, "lineno", 0)),
                            "expression": expr,
                            "dependencies": cls.extract_dependencies(expr),
                            "snippet": cls.line_window(lines, getattr(key, "lineno", getattr(node, "lineno", 1))),
                        })

            if isinstance(node, ast.Subscript):
                value_text = cls.safe_unparse(node.value)
                match = re.match(r"(df_[A-Za-z0-9_]+)\b", value_text)
                if not match:
                    continue
                dataframe_name = match.group(1)
                used_domain = cls.infer_domain_from_dataframe(dataframe_name)
                for column in cls.direct_string_slice_values(node.slice):
                    if not re.search(r"[A-Za-z]", column):
                        continue
                    domain_key = used_domain or dataframe_name
                    dataframe_refs.setdefault(domain_key, {}).setdefault(column, []).append({
                        "domain": domain,
                        "used_domain": used_domain,
                        "dataframe": dataframe_name,
                        "field": column,
                        "file": str(path),
                        "line": node.lineno,
                        "expression": cls.safe_unparse(node),
                        "snippet": cls.line_window(lines, node.lineno),
                    })

            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Attribute) and comparator.attr == "columns":
                        value = comparator.value
                        if isinstance(value, ast.Name) and value.id.startswith("df_"):
                            used_domain = cls.infer_domain_from_dataframe(value.id)
                            domain_key = used_domain or value.id
                            dataframe_refs.setdefault(domain_key, {}).setdefault(node.left.value, []).append({
                                "domain": domain,
                                "used_domain": used_domain,
                                "dataframe": value.id,
                                "field": node.left.value,
                                "file": str(path),
                                "line": node.lineno,
                                "expression": cls.safe_unparse(node),
                                "snippet": cls.line_window(lines, node.lineno),
                            })

        functions = cls.collect_functions(tree)
        reachable_ranges = cls.collect_reachable_function_ranges(tree)
        domain_logic_index = {
            "domain": domain,
            "fields": cls.filter_fields_by_ranges(fields, reachable_ranges),
            "dependencies": cls.filter_dependencies_by_ranges(dataframe_refs, reachable_ranges),
            "functions": [
                item for item in functions
                if cls.line_in_ranges(int(item.get("line") or 0), reachable_ranges)
            ],
            "columns": cls.collect_list_assignments(tree),
            "operations": cls.collect_domain_operations(tree, lines, domain, reachable_ranges),
        }

        file_index = {
            "domain": domain,
            "fields": fields,
            "dependencies": dataframe_refs,
            "functions": functions,
            "columns": cls.collect_list_assignments(tree),
            "operations": cls.collect_domain_operations(tree, lines, domain),
        }
        local_assignments, function_returns = cls.collect_local_assignments_and_returns(tree, lines)
        file_index["local_assignments"] = local_assignments
        file_index["function_returns"] = function_returns
        file_index["domain_logic"] = cls.build_domain_logic_payload(domain_logic_index)
        return file_index

    @classmethod
    def build_index(cls) -> dict:
        """
        扫描源码目录并构建完整索引。
        """
        root = cls.get_source_root()
        index = {
            "fields": {},
            "dependencies": {},
            "domain_logic": {},
            "local_assignments": {},
            "function_returns": {},
            "source_root": str(root)
        }
        if not root.exists():
            return index

        skip_names = {"__init__.py", "domain_mapping.py"}
        for path in sorted(root.glob("*.py")):
            if path.name in skip_names or path.stem.endswith("_copy"):
                continue
            file_index = cls.scan_file(path)
            domain = file_index["domain"]
            for field, entries in file_index["fields"].items():
                index["fields"].setdefault(domain, {}).setdefault(field, []).extend(entries)
            for used_domain, columns in file_index["dependencies"].items():
                for field, entries in columns.items():
                    index["dependencies"].setdefault(domain, {}).setdefault(used_domain, {}).setdefault(field, []).extend(entries)
            index["domain_logic"][domain] = file_index.get("domain_logic") or {}
            index["local_assignments"][domain] = file_index.get("local_assignments") or {}
            index["function_returns"][domain] = file_index.get("function_returns") or {}
        return index

    @classmethod
    def get_index(cls) -> dict:
        """
        返回缓存索引；首次调用时自动构建。
        """
        if cls._index_cache is None:
            cls._index_cache = cls.build_index()
        return cls._index_cache

    @classmethod
    def find_field(cls, domain: str | None, field: str | None) -> dict | None:
        """
        查询某个域字段的代码赋值逻辑。
        """
        if not domain or not field:
            return None
        entries = cls.get_index().get("fields", {}).get(domain.upper(), {}).get(field.upper(), [])
        if not entries:
            return None
        return {"domain": domain.upper(), "field": field.upper(), "entries": entries}

    @classmethod
    def find_dependency(cls, target_domain: str | None, used_domain: str | None) -> dict | None:
        """
        查询 target_domain 代码中使用 used_domain 哪些字段。
        """
        if not target_domain or not used_domain:
            return None
        fields = cls.get_index().get("dependencies", {}).get(target_domain.upper(), {}).get(used_domain.upper(), {})
        if not fields:
            return None
        return {
            "target_domain": target_domain.upper(),
            "used_domain": used_domain.upper(),
            "fields": fields,
        }

    @classmethod
    def find_domain_logic(cls, domain: str | None) -> dict | None:
        """
        查询某个域的通用源码级转换逻辑摘要。
        """
        if not domain:
            return None
        payload = cls.get_index().get("domain_logic", {}).get(domain.upper())
        if not payload:
            return None
        return payload

    @classmethod
    def find_variable_trace(cls, domain: str | None, variable: str | None, key: str | None = None) -> dict | None:
        """
        查询字段表达式依赖的本地变量来源，并展开函数 return 分支。
        例如 VSTPT = study_day_info['tpt'] 会追到 study_day_info = resolve_vs_timing(...)
        以及 resolve_vs_timing/parse_vs_timepoint_info 返回字典里的 tpt 分支。
        """
        if not domain or not variable:
            return None
        index = cls.get_index()
        domain_key = domain.upper()
        assignments = index.get("local_assignments", {}).get(domain_key, {}).get(variable, [])
        returns = index.get("function_returns", {}).get(domain_key, {})
        if not assignments:
            return None

        expanded_returns = []
        visited = set()

        def expand_function(function_name: str, depth: int = 0):
            if not function_name or depth > 3 or function_name in visited:
                return
            visited.add(function_name)
            for item in returns.get(function_name, []):
                value = item.get("dict_items", {}).get(key) if key else None
                if key and value is None:
                    call_match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\(", str(item.get("expression") or ""))
                    if call_match and call_match.group(1) in returns:
                        expand_function(call_match.group(1), depth + 1)
                    continue
                expanded_returns.append({
                    "function": function_name,
                    "line": item.get("line"),
                    "key": key,
                    "value": value,
                    "expression": item.get("expression"),
                    "snippet": item.get("snippet"),
                })
                for candidate in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\(", str(value or item.get("expression") or "")):
                    if candidate in returns:
                        expand_function(candidate, depth + 1)

        for assignment in assignments:
            match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\(", assignment.get("expression") or "")
            if match:
                expand_function(match.group(1))

        return {
            "variable": variable,
            "key": key,
            "assignments": assignments,
            "returns": expanded_returns,
        }

    @classmethod
    def find_field_dependents(cls, domain: str | None, field: str | None) -> list[dict]:
        """
        查找同域里表达式直接引用目标字段的输出字段。
        用于字段级回答的相关输出，不再从附近代码粗暴抓字段名。
        """
        if not domain or not field:
            return []
        domain_key = domain.upper()
        field_key = field.upper()
        domain_fields = cls.get_index().get("fields", {}).get(domain_key, {})
        dependents = []
        for candidate, entries in domain_fields.items():
            if candidate == field_key:
                continue
            for entry in entries:
                expression = str(entry.get("expression") or "")
                if re.search(rf"\b{re.escape(field_key)}\b", expression):
                    dependents.append({
                        "field": candidate,
                        "line": entry.get("line"),
                        "expression": expression,
                    })
                    break
        return sorted(dependents, key=lambda item: (str(item["field"]), int(item.get("line") or 0)))
