class LedgerEntry {
  const LedgerEntry({
    required this.id,
    required this.type,
    required this.amount,
    required this.referenceId,
    required this.balanceAfter,
    required this.createdAt,
  });

  final int id;
  final String type;
  final double amount;
  final String? referenceId;
  final double balanceAfter;
  final DateTime createdAt;

  factory LedgerEntry.fromJson(Map<String, dynamic> json) {
    return LedgerEntry(
      id: json['id'] as int,
      type: json['type'] as String,
      amount: double.parse(json['amount'].toString()),
      referenceId: json['reference_id'] as String?,
      balanceAfter: double.parse(json['balance_after'].toString()),
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}

class Statement {
  const Statement({
    required this.items,
    required this.page,
    required this.pageSize,
    required this.total,
  });

  final List<LedgerEntry> items;
  final int page;
  final int pageSize;
  final int total;

  factory Statement.fromJson(Map<String, dynamic> json) {
    return Statement(
      items: (json['items'] as List)
          .map((e) => LedgerEntry.fromJson(e as Map<String, dynamic>))
          .toList(),
      page: json['page'] as int,
      pageSize: json['page_size'] as int,
      total: json['total'] as int,
    );
  }
}
