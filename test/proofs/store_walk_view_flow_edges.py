"""Traversal edges for view flow edges."""


BINARY_AND_RIGHT_WALK_EDGE = (
    "if binary_operator == TokenKind.And:",
    "table <- chv_walk_expression(right, in_region, ref_params, binders, owned, view_names, view_values, right_flow, summary, table)",
)

BINARY_RIGHT_VIEW_EDGES = (
    ("if binary_operator == TokenKind.And:", "right_may_be_owned_view <- right_flow.last_value_may_be_owned_view"),
    ("if binary_operator != TokenKind.And:", "right_may_be_owned_view <- flow.last_value_may_be_owned_view"),
)

BINARY_OPERATOR_FALLBACK_EDGES = (
    ("Expr.Binary(left, binary_operator, right, _):", "binary_arguments: darray[Ast::Expr] = [left, right]"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_owned_views: darray[bool] = [left_may_be_owned_view, right_may_be_owned_view]"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_alias_refs: darray[bool] = [left_may_alias_ref, right_may_alias_ref]"),
    ("Expr.Binary(left, binary_operator, right, _):", "if binary_rhs_is_runtime_value and binary_operator != TokenKind.And and binary_operator != TokenKind.Or and not chv_binary_operator_returns_bool(binary_operator, right) and not binary_is_range:"),
    ("if binary_rhs_is_runtime_value and binary_operator != TokenKind.And and binary_operator != TokenKind.Or and not chv_binary_operator_returns_bool(binary_operator, right) and not binary_is_range:", "table <- chv_check_unknown_call(binary_arguments, binary_owned_views, binary_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
)

BINARY_NON_RUNTIME_TARGET_EDGES = (
    ("can Abort.Panic:", "return operator == TokenKind.Is or operator == TokenKind.As"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_rhs_is_runtime_value: bool = not chv_binary_operator_has_non_runtime_target(binary_operator)"),
)

CONSTRUCT_VIEW_TAINT_EDGES = (
    ("Expr.Construct(_, fields, _):", "for field in fields |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for field in fields |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(field.value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for field in fields |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.Construct(_, fields, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
)

RECORD_UPDATE_VIEW_TAINT_EDGES = (
    ("Expr.RecordUpdate(base, fields, _):", "table <- chv_walk_expression(base, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.RecordUpdate(base, fields, _):", "aggregate_may_be_owned_view: mutable bool = flow.last_value_may_be_owned_view"),
    ("Expr.RecordUpdate(base, fields, _):", "for field in fields |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for field in fields |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(field.value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for field in fields |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.RecordUpdate(base, fields, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
)

FIELD_PROJECTION_VIEW_TAINT_EDGES = (
    ("Expr.Field(_, _, _):", "root_name: sview = chv_place_root(argument)"),
    ("Expr.Field(_, _, _):", "index: usize = chv_flow_latest(flow, root_name) if root_name != \"\" else flow.names.count"),
    ("Expr.Field(_, _, _):", "return index < flow.names.count and flow.may_owned_view[index]"),
)

ARRAY_VIEW_TAINT_EDGES = (
    ("Expr.Array(elements, _):", "for element in elements |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(element, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.Array(elements, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
    ("Expr.Tuple(elements, _):", "for element in elements |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(element, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)", 1),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or flow.last_value_may_be_owned_view", 1),
    ("Expr.Tuple(elements, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
    ("Expr.SetLit(elements, _):", "for element in elements |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(element, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)", 2),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or flow.last_value_may_be_owned_view", 2),
    ("Expr.SetLit(elements, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
)

DICT_VIEW_TAINT_EDGES = (
    ("Expr.DictLit(entries, _):", "for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(entry.key, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:", "key_may_be_owned_view: bool = flow.last_value_may_be_owned_view"),
    ("for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(entry.value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or key_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.DictLit(entries, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
)

COMPREHENSION_VIEW_TAINT_EDGES = (
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "table <- chv_walk_expression(body, in_region, comprehension_ref_params, comprehension_binders, comprehension_owned, comprehension_view_names, comprehension_view_values, comprehension_flow, summary, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "body_may_be_owned_view: bool = comprehension_flow.last_value_may_be_owned_view"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "flow.last_value_may_be_owned_view <- body_may_be_owned_view"),
)

COMPREHENSION_BINDER_VIEW_TAINT_EDGES = (
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "table <- chv_walk_expression(iterable, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "iterable_may_yield_owned_view: bool = element_facts.may_owned_view if element_facts.known else chv_iterable_element_may_be_owned_view(iterable, flow, view_names, view_values, flow.last_value_may_be_owned_view, 0)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "chv_flow_bind(comprehension_flow, variable, false, iterable_may_yield_owned_view, iterable_may_yield_alias_reference)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "table <- chv_walk_expression(body, in_region, comprehension_ref_params, comprehension_binders, comprehension_owned, comprehension_view_names, comprehension_view_values, comprehension_flow, summary, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "body_may_be_owned_view: bool = comprehension_flow.last_value_may_be_owned_view"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "flow.last_value_may_be_owned_view <- body_may_be_owned_view"),
)

IDENTIFIER_VIEW_TAINT_EDGES = (
    ("Expr.Ident(bound_name, _):", "index: usize = chv_flow_latest(flow, bound_name)"),
    ("Expr.Ident(bound_name, _):", "return index < flow.names.count and flow.may_owned_view[index]"),
)

METHOD_CALL_VIEW_RESULT_EDGES = (
    ("Expr.Call(Expr.Field(receiver, _, _), call_arguments, _, _):", "receiver_root: sview = chv_place_root(receiver)"),
    ("Expr.Call(Expr.Field(receiver, _, _), call_arguments, _, _):", "receiver_index: usize = chv_flow_latest(flow, receiver_root) if receiver_root != \"\" else flow.names.count"),
    ("Expr.Call(Expr.Field(receiver, _, _), call_arguments, _, _):", "receiver_may_be_owned: bool = chv_is_owned_view(receiver, flow, depth + 1) or (receiver_index < flow.names.count and (flow.owned[receiver_index] or flow.may_owned_view[receiver_index]))"),
    ("Expr.Call(Expr.Field(receiver, _, _), call_arguments, _, _):", "arguments_may_be_owned: bool = any call_argument in call_arguments where chv_is_owned_view(call_argument, flow, depth + 1)"),
    ("Expr.Call(Expr.Field(receiver, _, _), call_arguments, _, _):", "return receiver_may_be_owned or arguments_may_be_owned"),
)

CALLABLE_VIEW_RESULT_EDGES = (
    ("Expr.Call(arguments: call_arguments, _):", "return any call_argument in call_arguments where chv_is_owned_view(call_argument, flow, depth + 1)"),
)

CALL_RESULT_VIEW_TAINT_EDGES = (
    ("Expr.Call(callee, arguments, _, _):", "result_may_be_owned_view: bool = chv_is_owned_view(expression, flow, 0) or (method_found and receiver_may_be_owned_view and (method_name == \"as_sview\" or method_name == \"as_cstr\" or method_name == \"view\")) or callee_may_be_owned_view"),
    ("for argument in arguments |table, argument_may_alias_refs, argument_owned_views, flow, arguments_may_be_owned_view, arguments_may_contain_alias_reference| -> table:", "arguments_may_be_owned_view <- arguments_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.Call(callee, arguments, _, _):", "flow.last_value_may_be_owned_view <- result_may_be_owned_view or arguments_may_be_owned_view"),
)

CALL_RESULT_CALLEE_JOIN_EDGE = (
    "Expr.Call(callee, arguments, _, _):",
    "result_may_be_owned_view: bool = chv_is_owned_view(expression, flow, 0) or (method_found and receiver_may_be_owned_view and (method_name == \"as_sview\" or method_name == \"as_cstr\" or method_name == \"view\")) or callee_may_be_owned_view",
)

CALL_CALLEE_INDEXED_VIEW_EDGES = (
    ("match callee:", "Expr.Index(head, index, _):"),
    ("Expr.Index(head, index, _):", "table <- chv_walk_call_callee(head, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, receiver_owned_view, receiver_may_alias_reference, callee_may_be_owned_view, table)"),
    ("Expr.Index(head, index, _):", "head_may_be_owned_view: bool = callee_may_be_owned_view or chv_is_owned_view(head, flow, 0)"),
    ("Expr.Index(head, index, _):", "index_may_be_owned_view: mutable bool = false"),
    ("Expr.Index(head, index, _):", "if not index_receiver_is_type_application(head):"),
    ("if not index_receiver_is_type_application(head):", "table <- chv_walk_expression(index, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("if not index_receiver_is_type_application(head):", "index_may_be_owned_view <- flow.last_value_may_be_owned_view"),
    ("if not index_receiver_is_type_application(head):", "indexed_arguments: darray[Ast::Expr] = [head, index]"),
    ("if not index_receiver_is_type_application(head):", "indexed_owned_views: darray[bool] = [head_may_be_owned_view, index_may_be_owned_view]"),
    ("if not index_receiver_is_type_application(head):", "indexed_alias_refs: darray[bool] = [chv_expression_may_alias_ref(head, ref_params, flow, table, 0), false]"),
    ("if not index_receiver_is_type_application(head):", "table <- chv_check_unknown_call(indexed_arguments, indexed_owned_views, indexed_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
    ("Expr.Index(head, index, _):", "callee_may_be_owned_view <- head_may_be_owned_view or index_may_be_owned_view"),
    ("match callee:", "Expr.IndexN(head, arguments, _):"),
    ("Expr.IndexN(head, arguments, _):", "table <- chv_walk_call_callee(head, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, receiver_owned_view, receiver_may_alias_reference, callee_may_be_owned_view, table)"),
    ("Expr.IndexN(head, arguments, _):", "head_may_be_owned_view: bool = callee_may_be_owned_view or chv_is_owned_view(head, flow, 0)"),
    ("Expr.IndexN(head, arguments, _):", "# In call position IndexN is explicit generic application. Its"),
    ("Expr.IndexN(head, arguments, _):", "# bracket arguments are type/shape inputs and never runtime values."),
    ("Expr.IndexN(head, arguments, _):", "callee_may_be_owned_view <- head_may_be_owned_view"),
    ("Expr.IndexN(head, arguments, _):", "callee_value_may_be_owned_view: bool = callee_may_be_owned_view"),
    ("Expr.IndexN(head, arguments, _):", "flow.last_value_may_be_owned_view <- callee_value_may_be_owned_view"),
)

STATIC_EFFECT_RESULT_VIEW_TAINT_EDGES = (
    ("Expr.StaticEffectCall(candidates: candidates, arguments: arguments, argument_names: argument_names, _):", "runtime_children: darray[Ast::Expr] = Ast::effect_runtime_children(candidates, arguments)"),
    ("for child in runtime_children |table, runtime_owned_views, runtime_may_alias_refs|:", "runtime_may_be_owned_view <- runtime_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.StaticEffectCall(candidates: candidates, arguments: arguments, argument_names: argument_names, _):", "flow.last_value_may_be_owned_view <- runtime_may_be_owned_view"),
)

ASSIGN_VIEW_TAINT_EDGES = (
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "assigned_root: sview = chv_place_root(target)"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "projection_assignment: bool = assigned_name == \"\" and assigned_root != \"\""),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "previous_index: usize = chv_flow_latest(flow, assigned_root) if assigned_root != \"\" else flow.names.count"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "previous_may_owned_view <- flow.may_owned_view[previous_index] if previous_index < flow.names.count"),
    ("else:", "table <- chv_walk_expression(assigned_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)", 0),
    ("else:", "assigned_value_may_be_owned_view <- flow.last_value_may_be_owned_view", 0),
    ("for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_direct_alias_refs, parallel_contained_alias_refs, parallel_yield_alias_refs, parallel_yield_alias_knowns, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_direct_alias_reference, assigned_value_may_contain_alias_reference, assigned_value_may_yield_alias_reference, assigned_value_yield_alias_reference_known| -> table:", "value_may_be_owned_view: bool = flow.last_value_may_be_owned_view"),
    ("for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_direct_alias_refs, parallel_contained_alias_refs, parallel_yield_alias_refs, parallel_yield_alias_knowns, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_direct_alias_reference, assigned_value_may_contain_alias_reference, assigned_value_may_yield_alias_reference, assigned_value_yield_alias_reference_known| -> table:", "assigned_value_may_be_owned_view <- assigned_value_may_be_owned_view or value_may_be_owned_view"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "table <- chv_walk_expression(target, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "assigned_alias: bool = assigned_value_may_be_owned_view or ((operator != TokenKind.Assign or projection_assignment) and previous_may_owned_view)"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "if assigned_root != \"\":"),
    ("if assigned_root != \"\":", "elif assigned_index < flow.names.count:"),
    ("elif assigned_index < flow.names.count:", "flow.may_owned_view[assigned_index] <- assigned_alias or (projection_assignment and flow.may_owned_view[assigned_index])"),
)

PLACE_ROOT_PROJECTION_EDGES = (
    ("Expr.Field(object, _, _):", "return chv_place_root(object)"),
    ("Expr.Index(object, _, _):", "return chv_place_root(object)"),
    ("Expr.IndexN(object, _, _):", "return chv_place_root(object)"),
    ("Expr.Slice(object: object, _):", "return chv_place_root(object)"),
)

EFFECT_CANDIDATE_EDGES = (
    ("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "candidate_arguments.extend(candidate.captures)"),
    ("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "candidate_arguments.extend(arguments)"),
    ("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "chv_check_call_target(candidate.callee, candidate_arguments, candidate_owned_views, candidate_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table) if not chv_call_has_named_arguments(argument_names)"),
)

VIEW_FLOW_MERGE_EDGES = (
    ("while index < visible_count and index < target.names.count and index < left.names.count and index < right.names.count |index, target, left, right|:", "target.may_owned_view[index] <- left.may_owned_view[index] or right.may_owned_view[index]"),
)

REF_ALIAS_FLOW_MERGE_EDGES = (
    ("while index < visible_count and index < target.names.count and index < left.names.count and index < right.names.count |index, target, left, right|:", "target.may_alias_reference[index] <- left.may_alias_reference[index] or right.may_alias_reference[index]"),
)

REF_ALIAS_HELPER_EDGES = (
    ("_:", "if index < flow.names.count:"),
    ("if index < flow.names.count:", "return flow.may_alias_reference[index] or flow.may_contain_alias_reference[index]"),
    ("_:", "return any reference_parameter in ref_params where reference_parameter == root"),
    ("Expr.Call(_, _, _, _):", "return ref_params.count > 0"),
    ("Expr.Binary(left, binary_operator, right, _):", "return chv_expression_may_alias_ref(left, ref_params, flow, table, depth + 1) or chv_expression_may_alias_ref(right, ref_params, flow, table, depth + 1)"),
    ("Expr.Field(_, _, _) | Expr.Index(_, _, _) | Expr.IndexN(_, _, _) | Expr.Slice(_, _, _, _) | Expr.Block(_, _, _, _) | Expr.GetElse(_, _, _) | Expr.Match(_, _, _) | Expr.Catch(_, _, _) | Expr.StaticEffectCall(_, _, _, _, _, _):", "return ref_params.count > 0"),
    ("Expr.Binary(left, binary_operator, right, _):", "return false if chv_binary_operator_returns_bool(binary_operator, right)"),
    ("Expr.Unary(operator, operand, _):", "return false if operator == TokenKind.Not"),
    ("Expr.Tuple(elements, _) | Expr.Array(elements, _) | Expr.SetLit(elements, _):", "return any element in elements where chv_expression_may_alias_ref(element, ref_params, flow, table, depth + 1)"),
    ("Expr.DictLit(entries, _):", "return any entry in entries where chv_expression_may_alias_ref(entry.key, ref_params, flow, table, depth + 1) or chv_expression_may_alias_ref(entry.value, ref_params, flow, table, depth + 1)"),
    ("Expr.Construct(_, fields, _):", "return any field in fields where chv_expression_may_alias_ref(field.value, ref_params, flow, table, depth + 1)"),
    ("Expr.RecordUpdate(base, fields, _):", "return chv_expression_may_alias_ref(base, ref_params, flow, table, depth + 1) or any field in fields where chv_expression_may_alias_ref(field.value, ref_params, flow, table, depth + 1)"),
)

COMPREHENSION_REF_ALIAS_EDGES = (
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "iterable_may_yield_alias_reference: bool = chv_iterable_element_may_alias_reference(iterable, ref_params, flow, table, depth + 1)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "chv_flow_bind(comprehension_flow, variable, false, false, iterable_may_yield_alias_reference)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "chv_flow_bind_truthy_condition_binders(condition, comprehension_ref_params, comprehension_flow, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "return chv_expression_may_alias_ref(body, comprehension_ref_params, comprehension_flow, table, depth + 1)"),
)

COMPREHENSION_CONTAIN_ALIAS_EDGES = (
    ("can Memory.Allocate, Abort.Panic:", "return false if chv_flow_iterable_is_scalar_sview(expression, flow, depth + 1)"),
    ("if known_elements:", "element_count: usize = chv_known_iterable_shape_count(elements)"),
    ("for element_index in 0..<element_count |found, elements, ref_params, flow, table|:", "element: Ast::Expr = chv_known_iterable_shape_element(elements, element_index)"),
    ("for element_index in 0..<element_count |found, elements, ref_params, flow, table|:", "found <- found or chv_expression_may_contain_alias_ref(element, ref_params, flow, table, depth + 1)"),
    ("match expression:", "Expr.If(condition, then_value, else_value, _):"),
    ("Expr.If(condition, then_value, else_value, _):", "chv_flow_bind_truthy_condition_binders(condition, ref_params, then_flow, table)"),
    ("Expr.If(condition, then_value, else_value, _):", "return chv_expression_may_contain_alias_ref(then_value, ref_params, then_flow, table, depth + 1) or chv_expression_may_contain_alias_ref(else_value, ref_params, flow, table, depth + 1)"),
    ("Expr.Ident(name, _):", "if index < flow.names.count:"),
    ("if index < flow.names.count:", "return flow.may_contain_alias_reference[index] or flow.may_alias_reference[index]"),
    ("_:", "return chv_expression_may_alias_ref(expression, ref_params, flow, table, depth + 1)"),
)

ITERABLE_REF_ALIAS_EDGES = (
    ("if known_elements:", "element_count: usize = chv_known_iterable_shape_count(elements)"),
    ("for element_index in 0..<element_count |may_yield_alias_reference, elements, ref_params, flow, table|:", "element: Ast::Expr = chv_known_iterable_shape_element(elements, element_index)"),
    ("for element_index in 0..<element_count |may_yield_alias_reference, elements, ref_params, flow, table|:", "element_is_aggregate, nested_shape = chv_known_iterable_shape(element, depth + 1)"),
    ("for element_index in 0..<element_count |may_yield_alias_reference, elements, ref_params, flow, table|:", "may_yield_alias_reference <- may_yield_alias_reference or (not element_is_aggregate and chv_expression_may_direct_alias_ref(element, ref_params, flow, table, depth + 1))"),
    ("if known_elements:", "return may_yield_alias_reference"),
    ("can Memory.Allocate, Abort.Panic:", "return false if chv_flow_iterable_is_scalar_sview(iterable, flow, depth + 1)"),
    ("can Memory.Allocate, Abort.Panic:", "return chv_iterable_element_may_contain_alias_ref(iterable, ref_params, flow, table, depth + 1)"),
)

ITERABLE_CONTAIN_ALIAS_EDGES = (
    ("can Memory.Allocate, Abort.Panic:", "return false if chv_flow_iterable_is_scalar_sview(iterable, flow, depth + 1)"),
    ("if known_elements:", "element_count: usize = chv_known_iterable_shape_count(elements)"),
    ("for element_index in 0..<element_count |found, elements, ref_params, flow, table|:", "element: Ast::Expr = chv_known_iterable_shape_element(elements, element_index)"),
    ("for element_index in 0..<element_count |found, elements, ref_params, flow, table|:", "found <- found or chv_expression_may_contain_alias_ref(element, ref_params, flow, table, depth + 1)"),
    ("match iterable:", "Expr.Ident(name, _):"),
    ("match iterable:", "Expr.Paren(inner, _) | Expr.Move(inner, _):"),
    ("Expr.Paren(inner, _) | Expr.Move(inner, _):", "return chv_iterable_element_may_contain_alias_ref(inner, ref_params, flow, table, depth + 1)"),
    ("match iterable:", "Expr.If(condition, then_value, else_value, _):"),
    ("Expr.If(condition, then_value, else_value, _):", "then_flow: mutable CHVViewFlow = chv_flow_clone(flow)"),
    ("Expr.If(condition, then_value, else_value, _):", "chv_flow_bind_truthy_condition_binders(condition, ref_params, then_flow, table)"),
    ("Expr.If(condition, then_value, else_value, _):", "return chv_iterable_element_may_contain_alias_ref(then_value, ref_params, then_flow, table, depth + 1) or chv_iterable_element_may_contain_alias_ref(else_value, ref_params, flow, table, depth + 1)"),
    ("Expr.Ident(name, _):", "index: usize = chv_flow_latest(flow, name)"),
    ("Expr.Ident(name, _):", "if index < flow.names.count:"),
    ("if index < flow.names.count:", "return flow.may_contain_alias_reference[index]"),
    ("can Memory.Allocate, Abort.Panic:", "return chv_expression_may_contain_alias_ref(iterable, ref_params, flow, table, depth + 1)"),
)

TYPE_ALIAS_ITERABLE_COLLISION_EDGES = (
    ("can Memory.Allocate, Abort.Panic:", "return (true, true) if not known and chv_type_alias_name_count(type_expression, alias_names) > 0"),
)

GETELSE_RECOVERY_TERMINATION_EDGES = (
    ("Expr.GetElse(guarded, recovery, _):", "recovery_terminates: bool = statements_terminate(recovery, table)"),
    ("Expr.GetElse(guarded, recovery, _):", "branch_value_may_be_owned <- branch_value_may_be_owned or recovery_flow.last_value_may_be_owned_view if not recovery_terminates"),
    ("Expr.GetElse(guarded, recovery, _):", "chv_flow_set_merge(flow, guarded_flow, recovery_flow, branch_mark) if not recovery_terminates"),
    ("Expr.GetElse(guarded, recovery, _):", "chv_flow_set_merge(flow, guarded_flow, guarded_flow, branch_mark) if recovery_terminates"),
)

SCALAR_SVIEW_FLOW_EDGES = (
    ("Expr.Ident(name, _):", "index: usize = chv_flow_latest(flow, name)"),
    ("Expr.Ident(name, _):", "if index < flow.names.count:"),
    ("if index < flow.names.count:", "return flow.may_be_scalar_sview[index]"),
    ("Expr.Ident(name, _):", "return chv_iterable_is_scalar_sview(expression, view_names, view_values, depth + 1)"),
)

VIEW_ALIAS_BINARY_EDGES = (
    ("Expr.Binary(left, binary_operator, right, _):", "return chv_is_owned_view(left, flow, depth + 1) or chv_is_owned_view(right, flow, depth + 1)"),
    ("Expr.Binary(left, binary_operator, right, _):", "return false if chv_binary_operator_returns_bool(binary_operator, right)"),
)

INDEX_OPERATOR_EDGES = (
    ("Expr.Index(object, index, _):", "table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Index(object, index, _):", "if not index_receiver_is_type_application(object):"),
    ("if not index_receiver_is_type_application(object):", "table <- chv_walk_expression(index, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)", 0),
    ("if not index_receiver_is_type_application(object):", "indexed_arguments: darray[Ast::Expr] = [object, index]", 0),
    ("if not index_receiver_is_type_application(object):", "indexed_owned_views: darray[bool] = [object_may_be_owned_view, index_may_be_owned_view]", 0),
    ("if not index_receiver_is_type_application(object):", "indexed_alias_refs: darray[bool] = [object_may_alias_ref, false]", 0),
    ("if not index_receiver_is_type_application(object):", "table <- chv_check_unknown_call(indexed_arguments, indexed_owned_views, indexed_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)", 0),
    ("Expr.IndexN(object, arguments, _):", "table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.IndexN(object, arguments, _):", "if not index_receiver_is_type_application(object):"),
    ("if not index_receiver_is_type_application(object):", "for argument in arguments |table|:", 1),
    ("for argument in arguments |table|:", "table <- chv_walk_expression(argument, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
)

INDEX_VIEW_RESULT_EDGES = (
    ("Expr.Index(object, index, _):", "index_may_be_owned_view: mutable bool = false"),
    ("Expr.Index(object, index, _):", "if not index_receiver_is_type_application(object):"),
    ("if not index_receiver_is_type_application(object):", "index_may_be_owned_view <- chv_is_owned_view(index, flow, depth + 1)"),
    ("Expr.Index(object, index, _):", "return chv_is_owned_view(object, flow, depth + 1) or index_may_be_owned_view"),
)

INDEXN_VIEW_RESULT_EDGES = (
    ("Expr.IndexN(object, arguments, _):", "# IndexN represents multi-index selection or generic application. Unlike"),
    ("Expr.IndexN(object, arguments, _):", "# single-key Index, it does not lower through the __index__ protocol, so"),
    ("Expr.IndexN(object, arguments, _):", "# selector/type arguments cannot become the returned view's storage."),
    ("Expr.IndexN(object, arguments, _):", "return chv_is_owned_view(object, flow, depth + 1)"),
)

INDEXN_VIEW_WALK_EDGES = (
    ("Expr.IndexN(object, arguments, _):", "flow.last_value_may_be_owned_view <- object_may_be_owned_view or chv_is_owned_view(expression, flow, 0)"),
)

UNARY_NEGATION_EDGES = (
    ("Expr.Unary(operator, operand, _):", "table <- chv_walk_expression(operand, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Unary(operator, operand, _):", "operand_may_be_owned_view: bool = flow.last_value_may_be_owned_view"),
    ("Expr.Unary(operator, operand, _):", "unary_result_may_be_owned_view: bool = operator != TokenKind.Not"),
    ("Expr.Unary(operator, operand, _):", "flow.last_value_may_be_owned_view <- operand_may_be_owned_view and unary_result_may_be_owned_view"),
)

BINARY_VIEW_WALK_EDGES = (
    ("Expr.Binary(left, binary_operator, right, _):", "left_may_be_owned_view: bool = flow.last_value_may_be_owned_view"),
    ("Expr.Binary(left, binary_operator, right, _):", "right_may_be_owned_view: mutable bool = false"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_result_is_bool: bool = chv_binary_operator_returns_bool(binary_operator, right)"),
    ("Expr.Binary(left, binary_operator, right, _):", "flow.last_value_may_be_owned_view <- (left_may_be_owned_view or right_may_be_owned_view) if not binary_result_is_bool and not binary_is_range else false"),
)

BINARY_BOOLEAN_RESULT_EDGES = (
    ("Expr.Binary(left, binary_operator, right, _):", BINARY_VIEW_WALK_EDGES[2][1]),
    ("can Memory.Allocate, Abort.Panic:", "boolean_operator: bool = operator == TokenKind.EqEq or operator == TokenKind.BangEq or operator == TokenKind.Lt or operator == TokenKind.Gt or operator == TokenKind.LtEq or operator == TokenKind.GtEq or operator == TokenKind.In or operator == TokenKind.Is or operator == TokenKind.And or operator == TokenKind.Or"),
    ("can Memory.Allocate, Abort.Panic:", "return boolean_operator or (operator == TokenKind.As and not chv_is_reinterpret_target_marker(right))"),
    ("Expr.Binary(left, binary_operator, right, _):", BINARY_VIEW_WALK_EDGES[3][1]),
)

REINTERPRET_TARGET_MARKER_EDGES = (
    ("match target:", "Expr.Ident(name, _):"),
    ("match target:", "_:"),
    ("Expr.Ident(name, _):", "return name == \"&\" or name == \"!\""),
    ("_:", "return false"),
)

UNARY_VIEW_RESULT_EDGES = (
    ("Expr.Unary(operator, operand, _):", "return chv_is_owned_view(operand, flow, depth + 1)"),
    ("Expr.Unary(operator, operand, _):", "return false if operator == TokenKind.Not"),
)

REF_ALIAS_ADDRESS_EDGES = (
    ("Expr.Unary(operator, operand, _):", "return chv_expression_may_alias_ref(operand, ref_params, flow, table, depth + 1)"),
    ("Expr.Unary(operator, operand, _):", "return false if operator == TokenKind.Not"),
)

SUMMARY_CALL_EDGES = (
    ("while target < call_arguments.count |target, table, source_cache_ready, source_checked, source_is_owned_view| -> table:", "if sts_is_writable(summary, callee_name, target) and not target_is_owned_local:"),
    ("if sts_is_writable(summary, callee_name, target) and not target_is_owned_local:", "if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow, table):"),
    ("while source < call_arguments.count |source, table, source_is_owned_view, source_checked| -> table:", "if source != target and sts_has_pair(summary, callee_name, target, source) and not sts_reads_reference_free(summary, callee_name, source):"),
    ("if source != target and sts_has_pair(summary, callee_name, target, source) and not sts_reads_reference_free(summary, callee_name, source):", "if not source_checked[source]:"),
    ("if not source_checked[source]:", "source_is_owned_view[source] <- chv_owned_view_at(call_arguments, argument_owned_views, source, flow)"),
)

OVERLOAD_SUMMARY_EDGES = (
    ("for function in functions |summary, summarised, summarised_unreadable, function_owners, table|:", "match function:"),
    ("match function:", "Decl.Func(name: function_name, params: function_parameters, body: function_body, pos: function_pos, _):"),
    ("if writable_found and function_parameters.count > 1:", "summarised.push(function)"),
    ("for function_index in 0..<summarised.count |function_index, more_rows, summary, summarised, summarised_unreadable, function_owners, reference_sites, table|:", "match summarised[function_index]:"),
    ("match summarised[function_index]:", "Decl.Func(name: function_name, params: function_parameters, body: function_body, _):"),
    ("Decl.Func(name: function_name, params: function_parameters, body: function_body, _):", "more_rows <- true if (sts_summarise_function(function_name, function_parameters, function_body, summarised_unreadable[function_index], function_owners[function_index], reference_sites, table, summary) can Global{Read,Write})"),
)

CALLEE_DISPATCH_EDGES = (
    ("Expr.Ident(callee_name, _):", "table <- chv_check_named_call(callee_name, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Scope(_, scoped_name, _):", "table <- chv_check_named_call(scoped_name, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Index(head, _, _):", "table <- chv_check_named_callee(head, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.IndexN(head, _, _):", "table <- chv_check_named_callee(head, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Paren(inner, _):", "table <- chv_check_named_callee(inner, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("_:", "table <- chv_check_unknown_call(call_arguments, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
)

FIELD_UNKNOWN_CALL_EDGES = (
    ("Expr.Field(receiver, method, _):", "method_arguments: mutable darray[Ast::Expr] = [receiver]"),
    ("Expr.Field(receiver, method, _):", "method_arguments.extend(call_arguments)"),
    ("Expr.Field(receiver, method, _):", "method_owned_views: mutable darray[bool] = [method_receiver_owned_view]"),
    ("Expr.Field(receiver, method, _):", "method_owned_views.extend(argument_owned_views)"),
    ("Expr.Field(receiver, method, _):", "method_may_alias_refs: mutable darray[bool] = [method_receiver_may_alias_ref]"),
    ("Expr.Field(receiver, method, _):", "method_may_alias_refs.extend(argument_may_alias_refs)"),
    ("Expr.Field(receiver, method, _):", "if sts_is_declared(summary, method) and chv_has_direct_method_summary(receiver, method, binders, flow, table) and not chv_call_has_named_arguments(argument_names):"),
    ("else:", "table <- chv_check_unknown_call(method_arguments, method_owned_views, method_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
)

NAMED_CALL_EDGES = (
    ("if not chv_call_has_named_arguments(argument_names) and sts_is_declared(summary, callee_name) and not (any binder in binders where binder == callee_name):", "table <- chv_check_call_target(callee_name, call_arguments, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("else:", "table <- chv_check_unknown_call(call_arguments, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
)

NAMED_ARGUMENT_UNIFIER_EDGES = (
    ("Expr.Call(callee, arguments, argument_names, _):", "sts_unify_calls(callee, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.Call(callee, arguments, argument_names, _):", "for argument in arguments |classes, reference_sites|:"),
    ("Expr.Ident(callee_name, callee_position):", 'shadowed: bool = borrow_reference_site_is_local(reference_sites, function_owner, callee_position, table) or has_unreadable_binder'),
    ("Expr.Ident(callee_name, callee_position):", 'if sts_is_declared(summary, callee_name) and not shadowed and not (any argument_name in argument_names where argument_name != ""):') ,
    ('if sts_is_declared(summary, callee_name) and not shadowed and not (any argument_name in argument_names where argument_name != ""):', "pair_row: mutable u32 = sts_pair_first(summary, callee_name)"),
    ('if sts_is_declared(summary, callee_name) and not shadowed and not (any argument_name in argument_names where argument_name != ""):', "return"),
    ("_:", "sts_collect_names(expression, hidden_names)", 2),
    ("_:", "sts_unify_all(classes, hidden_names)", 2),
)

NAMED_ARGUMENT_STATIC_EFFECT_EDGES = (
    ("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "chv_check_call_target(candidate.callee, candidate_arguments, candidate_owned_views, candidate_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table) if not chv_call_has_named_arguments(argument_names)"),
    ("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "chv_check_unknown_call(candidate_arguments, candidate_owned_views, candidate_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table) if chv_call_has_named_arguments(argument_names)"),
)

UNKNOWN_CALL_EDGES = (
    ("for target in 0..<call_arguments.count |table| -> table:", "if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow, table):"),
    ("if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow, table):", "for source in 0..<call_arguments.count |table| -> table:"),
    ("for source in 0..<call_arguments.count |table| -> table:", "if source != target and chv_owned_view_at(call_arguments, argument_owned_views, source, flow):"),
    ("if source != target and chv_owned_view_at(call_arguments, argument_owned_views, source, flow):", "table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.AutoRegionStoreEscape, name: \"\", pos: at, line: at.line, expected: \"\", actual: \"\", state_code: (target + CHV_DIAGNOSTIC_ARGUMENT_NUMBER_BASE).u32()})"),
)

UNIFIER_FALLBACK_EDGES = (
    ("_:", "sts_collect_names(expression, hidden_names)", 2),
    ("_:", "sts_unify_all(classes, hidden_names)", 2),
)
