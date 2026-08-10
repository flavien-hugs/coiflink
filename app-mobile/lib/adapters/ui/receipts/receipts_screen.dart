// Écran UI : « Mes reçus » — reçus de paiement du client (US-5.5, #38 ·
// ADR-0040).
//
// Liste, **en lecture seule**, les reçus du client (via `ListMyReceipts`) : date,
// salon, montant. Le serveur ne renvoie que ses propres reçus (appartenance
// forcée serveur, §11.2/§11.3). Aucune règle métier ni appel HTTP direct ici ; le
// jeton n'est **jamais journalisé** (§11.1). Tapoter un reçu ouvre son détail
// (`ReceiptDetailScreen`), avec l'action « Partager ».

import 'package:flutter/material.dart';

import '../../../application/auth_session.dart';
import '../../../application/ports/receipt_gateway.dart';
import '../../../application/use_cases/get_receipt_detail.dart';
import '../../../application/use_cases/list_my_receipts.dart';
import '../../../domain/receipt/receipt.dart';
import '../booking/booking_flow_screen.dart' show LoginRequester;
import '../booking/booking_labels.dart';
import 'receipt_detail_screen.dart';

class ReceiptsScreen extends StatefulWidget {
  const ReceiptsScreen({
    super.key,
    required this.listMyReceipts,
    required this.getReceiptDetail,
    required this.session,
    required this.onRequireLogin,
  });

  final ListMyReceipts listMyReceipts;
  final GetReceiptDetail getReceiptDetail;
  final AuthSession session;
  final LoginRequester onRequireLogin;

  @override
  State<ReceiptsScreen> createState() => _ReceiptsScreenState();
}

class _ReceiptsScreenState extends State<ReceiptsScreen> {
  bool _loading = true;
  bool _needsLogin = false;
  String? _error;
  List<Receipt> _receipts = const <Receipt>[];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      _error = null;
      _needsLogin = false;
    });

    var token = await widget.session.currentToken();
    if (token == null) {
      if (!mounted) return;
      final ok = await widget.onRequireLogin(context);
      if (!ok) {
        _showNeedsLogin();
        return;
      }
      token = await widget.session.currentToken();
      if (token == null) {
        _showNeedsLogin();
        return;
      }
    }

    try {
      final items = await widget.listMyReceipts.call(accessToken: token);
      if (!mounted) return;
      setState(() {
        _receipts = items;
        _loading = false;
      });
    } on UnauthorizedException {
      await widget.session.clear();
      if (!mounted) return;
      setState(() {
        _loading = false;
        _needsLogin = true;
        _error = 'Session expirée, veuillez vous reconnecter.';
      });
    } on ReceiptGatewayException catch (exc) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = exc.message;
      });
    }
  }

  void _showNeedsLogin() {
    if (!mounted) return;
    setState(() {
      _loading = false;
      _needsLogin = true;
    });
  }

  void _openDetail(Receipt receipt) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ReceiptDetailScreen(
          paymentId: receipt.paymentId,
          getReceiptDetail: widget.getReceiptDetail,
          session: widget.session,
          onRequireLogin: widget.onRequireLogin,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Mes reçus')),
      body: SafeArea(child: _buildBody()),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_needsLogin) {
      return _CenteredAction(
        message: _error ?? 'Connectez-vous pour voir vos reçus.',
        actionLabel: 'Se connecter',
        onAction: _load,
      );
    }
    if (_error != null) {
      return _CenteredAction(
        message: _error!,
        actionLabel: 'Réessayer',
        onAction: _load,
      );
    }
    if (_receipts.isEmpty) {
      return const _CenteredMessage('Vous n\'avez aucun reçu pour le moment.');
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: _receipts.length,
        separatorBuilder: (_, _) => const SizedBox(height: 12),
        itemBuilder: (context, index) {
          final receipt = _receipts[index];
          return _ReceiptCard(
            receipt: receipt,
            onTap: () => _openDetail(receipt),
          );
        },
      ),
    );
  }
}

class _ReceiptCard extends StatelessWidget {
  const _ReceiptCard({required this.receipt, required this.onTap});

  final Receipt receipt;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: ListTile(
        onTap: onTap,
        title: Text(receipt.salonName, style: theme.textTheme.titleMedium),
        subtitle: Text(
          '${formatFullDate(receipt.paidAt)} — ${receipt.receiptNumber}',
        ),
        trailing: Text('${receipt.amount} FCFA'),
      ),
    );
  }
}

class _CenteredMessage extends StatelessWidget {
  const _CenteredMessage(this.message);

  final String message;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: <Widget>[
        const SizedBox(height: 48),
        Text(message, textAlign: TextAlign.center),
      ],
    );
  }
}

class _CenteredAction extends StatelessWidget {
  const _CenteredAction({
    required this.message,
    required this.actionLabel,
    required this.onAction,
  });

  final String message;
  final String actionLabel;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton(onPressed: onAction, child: Text(actionLabel)),
          ],
        ),
      ),
    );
  }
}
