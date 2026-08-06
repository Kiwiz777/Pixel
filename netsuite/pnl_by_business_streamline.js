/**
 * @NApiVersion 2.1
 * @NScriptType Suitelet
 *
 * P&L By Business Streamline (Sector / Project / Clinic)
 *
 * Dataset column map (custdataset18 — final structure):
 *   0  – trandate                                    (DD/MM/YYYY)
 *   1  – postingperiod                                (internal ID)
 *   2  – account                                      (internal ID)
 *   3  – entity
 *   4  – trandisplayname                              ("Invoice #INV41776")
 *   5  – type               (transaction type)
 *   6  – formula_0           (Account Type Amount Sign — netamount already sign-flipped for
 *                             Income; we recompute this ourselves so col 6 stays informational)
 *   7  – netamount
 *   8  – accounttype
 *   9  – cseg_emp_clinic_sec (Business Streamline segment VALUE INTERNAL ID — RAW, same join level as netamount/accounttype)
 *   10 – formula_1            (precomputed "Clinic: X" breadcrumb — informational only, not used for chain building)
 *   11 – id                   (OPTIONAL — transaction internal ID. If you add this column to the
 *                              dataset, every drill-down line links to the transaction record.
 *                              Everything else works without it.)
 *
 * Custom segment record: cseg_emp_clinic_sec
 *   - name                                  -> display name
 *   - custrecord_itp_business_strramline_type -> level (Sector / Project / Clinic)
 *   - parent                                -> parent record (next level up)
 *
 * DRILL-DOWN
 *   The report already holds every posting line it summarised, so the drill-down needs no second
 *   query and no second request. While pivoting, each line is also pushed into a compact,
 *   string-interned payload embedded in the page. Clicking an amount filters that payload in the
 *   browser and renders the transactions instantly. One dataset read per page load, same as before.
 */
define(['N/query', 'N/search', 'N/ui/serverWidget'], (query, search, serverWidget) => {
	const SEGMENT_RECTYPE = 'customrecord_cseg_emp_clinic_sec';
	const SEGMENT_TYPE_FIELD = 'custrecord_itp_business_strramline_type';
	const DATASET_ID = 'custdataset18';

	/* Dataset column indexes — named so the pivot and the drill payload can never drift apart. */
	const COL = {
		TRANDATE: 0,
		PERIOD: 1,
		ACCOUNT: 2,
		ENTITY: 3,
		DISPLAYNAME: 4,
		TYPE: 5,
		NETAMOUNT: 7,
		ACCOUNTTYPE: 8,
		SEGMENT: 9,
		TRANID: 11 // optional, see header note
	};

	/* Above this many posting lines the payload would bloat the page, so links are switched off and
	 * the report says why. Interned strings keep a typical line near 30 bytes. */
	const DRILL_MAX_EMBED = 20000;

	const LEVELS = ['Sector', 'Project', 'Clinic'];

	const SECTIONS = [
		{key: 'income', label: 'Income', signFlip: true},
		{key: 'cogs', label: 'Cost of Sales', signFlip: false},
		{key: 'gross', label: 'Gross Profit', virtual: true},
		{key: 'expense', label: 'Overheads', signFlip: false},
		{key: 'operating', label: 'Operating Profit', virtual: true},
		{key: 'othincome', label: 'Other Income', signFlip: true},
		{key: 'othexpense', label: 'Other Expenses', signFlip: false},
		{key: 'net', label: 'Net Profit / (Loss)', virtual: true}
	];

	const SECTION_BY_KEY = SECTIONS.reduce((m, s) => {
		m[s.key] = s;
		return m;
	}, {});

	/* Raw NetSuite transaction type codes -> readable labels. Falls back to the raw value, so it is
	 * harmless when the dataset already emits display text ("Invoice", "Item Fulfillment", …). */
	const TRAN_TYPE_LABELS = {
		CustInvc: 'Invoice',
		CustCred: 'Credit Memo',
		CustPymt: 'Customer Payment',
		CustDep: 'Customer Deposit',
		CashSale: 'Cash Sale',
		CashRfnd: 'Cash Refund',
		VendBill: 'Bill',
		VendCred: 'Bill Credit',
		VendPymt: 'Bill Payment',
		VendAuth: 'Vendor Return Auth',
		PurchOrd: 'Purchase Order',
		SalesOrd: 'Sales Order',
		RtnAuth: 'Return Authorization',
		Estimate: 'Estimate',
		Journal: 'Journal Entry',
		Check: 'Check',
		Deposit: 'Deposit',
		ExpRept: 'Expense Report',
		ItemShip: 'Item Fulfillment',
		ItemRcpt: 'Item Receipt',
		InvAdjst: 'Inventory Adjustment',
		InvTrnfr: 'Inventory Transfer',
		InvWksht: 'Inventory Worksheet',
		Build: 'Assembly Build',
		Unbuild: 'Assembly Unbuild',
		Transfer: 'Transfer'
	};

	const typeToSection = t => {
		switch ((t || '').toLowerCase().trim()) {
			case 'income':
				return 'income';
			case 'cost of goods sold':
			case 'costofgoodssold':
			case '_costofgoodssold':
			case 'cogs':
				return 'cogs';
			case 'expense':
			case '_expense':
			case 'expenses':
			case 'opex':
				return 'expense';
			case 'other income':
			case 'othincome':
			case '_otherincome':
				return 'othincome';
			case 'other expense':
			case 'othexpense':
			case '_otherexpense':
				return 'othexpense';
			default:
				return null;
		}
	};

	const esc = s =>
		String(s == null ? '' : s)
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;');

	const fmt = n => {
		const v = Number(n || 0);
		if (v === 0) return '-';
		const abs = Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
		return v < 0 ? '(' + abs + ')' : abs;
	};

	const parseDMY = s => {
		if (!s) return null;
		const p = String(s).split('/');
		if (p.length !== 3) return null;
		return parseInt(p[2] + p[1].padStart(2, '0') + p[0].padStart(2, '0'), 10);
	};

	const loadAllRows = datasetId => {
		const dataset = query.load({id: datasetId});
		const paged = dataset.runPaged({pageSize: 1000});
		const all = [];
		paged.pageRanges.forEach(pr => {
			paged.fetch({index: pr.index}).data.results.forEach(r => all.push(r));
		});
		return all;
	};

	/* ── Load the entire Business Streamline hierarchy once ── */
	const leafName = n => {
		const parts = String(n || '').split(' : ');
		return parts[parts.length - 1].trim();
	};

	const loadSegmentHierarchy = () => {
		const byId = {}; // id -> {id, name, level, parentId}
		const byNameLevel = {}; // "LEVEL::lowercased name" -> id  (used when dataset level is textual)
		const byName = {}; // "lowercased name" -> id             (fallback when dataset level is an internal ID, not text)

		search
			.create({
				type: SEGMENT_RECTYPE,
				filters: [['isinactive', 'is', 'F']],
				columns: ['internalid', 'name', SEGMENT_TYPE_FIELD, 'parent', 'custrecord_itp_business_strramline_type', 'custrecord_itp_bus_strem_grouping']
			})
			.run()
			.each(result => {
				const id = String(result.getValue('internalid'));
				const name = result.getValue('name') || '';
				const levelText = result.getText(SEGMENT_TYPE_FIELD);
				const levelValue = result.getValue(SEGMENT_TYPE_FIELD);
				const level = levelText || String(levelValue || '');
				const parentId = result.getValue('parent') ? String(result.getValue('parent')) : '';

				byId[id] = {id, name, level, parentId, _debugLevelText: levelText, _debugLevelValue: levelValue, grouping: result.getValue('custrecord_itp_bus_strem_grouping'), groupingText: result.getText('custrecord_itp_bus_strem_grouping')};
				byNameLevel[level.toLowerCase() + '::' + name.toLowerCase()] = id;
				byName[name.toLowerCase()] = id;
				return true;
			});

		return {byId, byNameLevel, byName};
	};

	/* ── Resolve a row's segment id (preferred) or name into {Sector, Project, Clinic} ──
	 *  Dataset now exposes the leaf segment record's internal ID directly, so we resolve
	 *  by exact ID match first (reliable), falling back to name-only match only if the
	 *  ID isn't found in the hierarchy map (e.g. stale cache, inactive record edge case). */
	const resolveChain = (hierarchy, segId, name, levelRaw, cache) => {
		const cacheKey = 'id:' + (segId || '') + '|name:' + (name || '');
		if (cache[cacheKey]) return cache[cacheKey];

		const chain = {Sector: '', Project: '', Clinic: ''};

		let startId = segId != null && hierarchy.byId[String(segId)] ? String(segId) : null;

		if (!startId && name) {
			const levelKey = levelRaw == null ? '' : String(levelRaw);
			startId = hierarchy.byNameLevel[levelKey.toLowerCase() + '::' + name.toLowerCase()] || hierarchy.byName[name.toLowerCase()];
		}

		if (!startId) {
			cache[cacheKey] = chain;
			return chain;
		}

		let cur = hierarchy.byId[startId];
		let guard = 0;
		const trace = [];
		while (cur && guard < 10) {
			trace.push('[id:' + cur.id + ' name:"' + cur.name + '" level:"' + cur.level + '" parentId:"' + cur.parentId + '"]');
			if (LEVELS.indexOf(cur.level) !== -1) chain[cur.level] = leafName(cur.name);
			if (!cur.parentId) break;
			cur = hierarchy.byId[cur.parentId];
			guard++;
		}
		chain._trace = trace.join(' -> ');

		cache[cacheKey] = chain;
		return chain;
	};

	/* ── Filter pipeline ── */

	const readFilters = params => ({
		fromPeriodId: params.custpage_from_period || '',
		toPeriodId: params.custpage_to_period || '',
		fromDateRaw: params.custpage_from_date || '',
		toDateRaw: params.custpage_to_date || '',
		level: params.custpage_level || 'Sector',
		sector: params.custpage_sector_filter || '',
		project: params.custpage_project_filter || '',
		clinic: params.custpage_clinic_filter || '',
		grouping: params.custpage_grouping_filter || ''
	});

	const filterRowsByDateWindow = (allRows, f) => {
		const fromDateInt = parseDMY(f.fromDateRaw);
		const toDateInt = parseDMY(f.toDateRaw);

		return allRows.filter(row => {
			const periodId = Number(row.values[COL.PERIOD] || 0);
			const tranDateInt = parseDMY(row.values[COL.TRANDATE]);

			if (f.fromPeriodId && periodId < Number(f.fromPeriodId)) return false;
			if (f.toPeriodId && periodId > Number(f.toPeriodId)) return false;
			if (fromDateInt && tranDateInt !== null && tranDateInt < fromDateInt) return false;
			if (toDateInt && tranDateInt !== null && tranDateInt > toDateInt) return false;
			return true;
		});
	};

	/**
	 * Applies the Sector / Project / Clinic / Grouping filters and stamps each surviving row with
	 * the column bucket it belongs to. `onSkipped` (optional) receives rows for debug reporting.
	 */
	const buildResolvedRows = (rows, hierarchy, chainCache, f, onSkipped) => {
		const resolved = [];

		rows.forEach(row => {
			const segId = row.values[COL.SEGMENT];
			const chain = resolveChain(hierarchy, segId, null, null, chainCache);

			if (onSkipped) onSkipped(row, segId, chain, f.level);

			if (f.sector && chain.Sector !== f.sector) return;
			if (f.project && chain.Project !== f.project) return;
			if (f.clinic && chain.Clinic !== f.clinic) return;

			const segmentRec = hierarchy.byId[String(segId)];
			if (f.grouping && (!segmentRec || segmentRec.grouping != f.grouping)) return;

			resolved.push({row, colValue: chain[f.level] || 'Unclassified', chain});
		});

		return resolved;
	};

	const loadAccounts = accountIds => {
		const accountMap = {};
		if (!accountIds.length) return accountMap;

		search
			.create({
				type: search.Type.ACCOUNT,
				filters: [['internalid', 'anyof', accountIds]],
				columns: ['internalid', 'number', 'name', 'displayname', 'type']
			})
			.run()
			.each(result => {
				accountMap[result.getValue('internalid')] = {
					number: result.getValue('number') || '',
					name: result.getValue('name') || '',
					displayname: result.getValue('displayname') || '',
					typeDisplay: result.getValue('type') || ''
				};
				return true;
			});

		return accountMap;
	};

	const accountLabelOf = (acct, accountId) => {
		const acctNum = acct.number || '';
		return acctNum ? acctNum + ' - ' + (acct.displayname || acct.name) : acct.displayname || acct.name || 'Account ' + accountId;
	};

	/** Section a posted row belongs to, using the dataset type first and the account record second. */
	const sectionOfRow = (row, acct) => typeToSection(String(row.values[COL.ACCOUNTTYPE] || '')) || typeToSection(acct ? acct.typeDisplay : '') || null;

	/* Record page per entity type, so a customer link doesn't point at the vendor form. */
	const ENTITY_URL_BY_TYPE = {
		CustJob: '/app/common/entity/custjob.nl?id=',
		Vend: '/app/common/entity/vendor.nl?id=',
		Employee: '/app/common/entity/employee.nl?id=',
		Partner: '/app/common/entity/partner.nl?id=',
		Contact: '/app/common/entity/contact.nl?id=',
		Group: '/app/common/entity/entitygroup.nl?id=',
		Project: '/app/accounting/project/project.nl?id='
	};

	/**
	 * "Cl203 UCP URGENT CARE PHARMACY" — the customer's own ID followed by its name.
	 * Accounts differ in where that lives: with auto-numbering `entityid` is just the code
	 * ("Cl203") and the name sits in `altname`; without it, `entityid` already holds the whole
	 * thing. Join them only when `altname` isn't already part of `entityid`, so neither setup
	 * produces "Cl203 UCP URGENT CARE PHARMACY UCP URGENT CARE PHARMACY".
	 */
	const entityDisplayName = r => {
		const eid = String(r.entityid || '').trim();
		const alt = String(r.altname || '').trim();
		if (!eid) return alt || String(r.id);
		if (!alt || eid === alt || eid.indexOf(alt) !== -1) return eid;
		return eid + ' ' + alt;
	};

	/**
	 * The dataset's entity column returns internal IDs. Resolve each to its display name and its
	 * record URL, so the drill-down shows "Cl199 NMDC Energy Saudi Ltd" linked to the customer.
	 * Values that are already text pass straight through; a failure returns its message rather
	 * than being swallowed, so a broken lookup is visible instead of silently showing raw ids.
	 */
	const resolveEntities = ids => {
		const map = {};
		let error = '';
		const numeric = ids.filter(v => /^\d+$/.test(String(v)));
		if (!numeric.length) return {map, error};

		for (let i = 0; i < numeric.length; i += 400) {
			const chunk = numeric.slice(i, i + 400);
			try {
				query
					.runSuiteQL({query: 'SELECT id, entityid, altname, type FROM entity WHERE id IN (' + chunk.join(',') + ')'})
					.asMappedResults()
					.forEach(r => {
						const base = ENTITY_URL_BY_TYPE[r.type];
						map[String(r.id)] = {
							name: entityDisplayName(r),
							url: base ? base + r.id : ''
						};
					});
			} catch (e) {
				error = e.message || String(e);
			}
		}
		return {map, error};
	};

	const periodNames = ids => {
		const map = {};
		const wanted = ids.filter(Boolean);
		if (!wanted.length) return map;
		try {
			search
				.create({type: 'accountingperiod', filters: [['internalid', 'anyof', wanted]], columns: ['internalid', 'periodname']})
				.run()
				.each(r => {
					map[String(r.getValue('internalid'))] = r.getValue('periodname');
					return true;
				});
		} catch (e) {
			/* non-fatal — the drill header just shows the raw ids */
		}
		return map;
	};

	/* ────────────────────────────────────────────────────────────────────────────
	 * Report
	 * ──────────────────────────────────────────────────────────────────────────── */

	const onRequest = context => {
		const form = serverWidget.createForm({title: 'P&L By Business Streamline'});

		form.addFieldGroup({id: 'custpage_periods', label: 'Periods'});
		form.addFieldGroup({id: 'custpage_filters', label: 'Filters'});
		form.addFieldGroup({id: 'custpage_streamline', label: 'Business Streamline'});

		const fFromPeriod = form.addField({
			id: 'custpage_from_period',
			type: serverWidget.FieldType.SELECT,
			label: 'Posting Period From',
			source: 'accountingperiod',
			container: 'custpage_periods'
		});
		const fToPeriod = form.addField({
			id: 'custpage_to_period',
			type: serverWidget.FieldType.SELECT,
			label: 'Posting Period To',
			source: 'accountingperiod',
			container: 'custpage_periods'
		});
		const fFromDate = form.addField({
			id: 'custpage_from_date',
			type: serverWidget.FieldType.DATE,
			label: 'Date From',
			container: 'custpage_filters'
		});
		const fToDate = form.addField({
			id: 'custpage_to_date',
			type: serverWidget.FieldType.DATE,
			label: 'Date To',
			container: 'custpage_filters'
		});

		const fLevel = form.addField({
			id: 'custpage_level',
			type: serverWidget.FieldType.SELECT,
			label: 'View By Level',
			container: 'custpage_streamline'
		});
		fLevel.addSelectOption({value: 'Sector', text: 'Sector'});
		fLevel.addSelectOption({value: 'Project', text: 'Project'});
		fLevel.addSelectOption({value: 'Clinic', text: 'Clinic'});

		const fSectorFilter = form.addField({
			id: 'custpage_sector_filter',
			type: serverWidget.FieldType.SELECT,
			label: 'Sector',
			container: 'custpage_streamline'
		});
		fSectorFilter.addSelectOption({value: '', text: ''});

		const fProjectFilter = form.addField({
			id: 'custpage_project_filter',
			type: serverWidget.FieldType.SELECT,
			label: 'Project',
			container: 'custpage_streamline'
		});
		fProjectFilter.addSelectOption({value: '', text: ''});

		const fClinicFilter = form.addField({
			id: 'custpage_clinic_filter',
			type: serverWidget.FieldType.SELECT,
			label: 'Clinic',
			container: 'custpage_streamline'
		});
		fClinicFilter.addSelectOption({value: '', text: ''});

		const fGroupingFilter = form.addField({
			id: 'custpage_grouping_filter',
			type: serverWidget.FieldType.SELECT,
			label: 'Grouping',
			container: 'custpage_streamline'
		});
		fGroupingFilter.addSelectOption({value: '', text: ''});

		fFromPeriod.updateLayoutType({layoutType: serverWidget.FieldLayoutType.STARTROW});
		fToPeriod.updateLayoutType({layoutType: serverWidget.FieldLayoutType.MIDROW});

		fFromDate.updateLayoutType({layoutType: serverWidget.FieldLayoutType.STARTROW});
		fToDate.updateLayoutType({layoutType: serverWidget.FieldLayoutType.MIDROW});

		fLevel.updateLayoutType({layoutType: serverWidget.FieldLayoutType.STARTROW});
		fSectorFilter.updateLayoutType({layoutType: serverWidget.FieldLayoutType.MIDROW});
		fProjectFilter.updateLayoutType({layoutType: serverWidget.FieldLayoutType.MIDROW});
		fClinicFilter.updateLayoutType({layoutType: serverWidget.FieldLayoutType.ENDROW});
		fGroupingFilter.updateLayoutType({layoutType: serverWidget.FieldLayoutType.ENDROW});

		const params = context.request.parameters;
		const f = readFilters(params);
		const levelRaw = f.level;
		const sectorFilterRaw = f.sector;
		const projectFilterRaw = f.project;
		const clinicFilterRaw = f.clinic;
		const groupingFilterRaw = f.grouping;

		fFromPeriod.defaultValue = f.fromPeriodId;
		fToPeriod.defaultValue = f.toPeriodId;
		fFromDate.defaultValue = f.fromDateRaw;
		fToDate.defaultValue = f.toDateRaw;
		fLevel.defaultValue = levelRaw;

		form.addSubmitButton({label: 'Run Report'});

		const fHtml = form.addField({
			id: 'custpage_html',
			type: serverWidget.FieldType.INLINEHTML,
			label: 'Report'
		});

		try {
			/* ── Hierarchy ── */
			const hierarchy = loadSegmentHierarchy();
			const chainCache = {};

			/* Populate Sector / Project / Clinic dropdown options, narrowed by what's already selected.
			 * Each hierarchy record's own chain is resolved (reusing resolveChain) so we know which
			 * Sector/Project a given Project/Clinic record belongs to, for narrowing the lists. */
			const sectorNames = new Set();
			const projectOptions = new Set(); // narrowed by sectorFilterRaw
			const clinicOptions = new Set(); // narrowed by sectorFilterRaw + projectFilterRaw
			const groupingOptions = {};

			Object.keys(hierarchy.byId).forEach(id => {
				const rec = hierarchy.byId[id];
				const recChain = resolveChain(hierarchy, id, null, null, chainCache);

				if (rec.level === 'Sector' && recChain.Sector) sectorNames.add(recChain.Sector);

				if (rec.level === 'Project' && recChain.Project) {
					if (!sectorFilterRaw || recChain.Sector === sectorFilterRaw) projectOptions.add(recChain.Project);
				}

				if (rec.level === 'Clinic' && recChain.Clinic) {
					const sectorOk = !sectorFilterRaw || recChain.Sector === sectorFilterRaw;
					const projectOk = !projectFilterRaw || recChain.Project === projectFilterRaw;
					if (sectorOk && projectOk) clinicOptions.add(recChain.Clinic);
				}
				if (rec.grouping) {
					groupingOptions[rec.grouping] = rec.groupingText;
				}
			});
			Object.keys(groupingOptions)
				.sort((a, b) => groupingOptions[a].localeCompare(groupingOptions[b]))
				.forEach(id => {
					fGroupingFilter.addSelectOption({
						value: id,
						text: groupingOptions[id]
					});
				});

			[...sectorNames].sort().forEach(n => fSectorFilter.addSelectOption({value: n, text: n}));
			[...projectOptions].sort().forEach(n => fProjectFilter.addSelectOption({value: n, text: n}));
			[...clinicOptions].sort().forEach(n => fClinicFilter.addSelectOption({value: n, text: n}));
			fSectorFilter.defaultValue = sectorFilterRaw;
			fProjectFilter.defaultValue = projectFilterRaw;
			fClinicFilter.defaultValue = clinicFilterRaw;
			fGroupingFilter.defaultValue = groupingFilterRaw;

			/* ── Dataset rows ── */
			const allRows = loadAllRows(DATASET_ID);
			const rows = filterRowsByDateWindow(allRows, f);

			/* ── Accounts ── */
			const accountIds = [...new Set(rows.map(r => r.values[COL.ACCOUNT]).filter(Boolean))];
			const accountMap = loadAccounts(accountIds);

			/* ── Resolve chain per row + apply Sector/Project filters + collect columns ── */
			const columnSet = new Set();
			const columnChains = {};
			const debugMode = params.custpage_debug === '1';
			const unmatchedStreamline = {};

			const debugCollector = !debugMode
				? null
				: (row, segId, chain, level) => {
						const matched = !!(chain.Sector || chain.Project || chain.Clinic);
						if (matched && chain[level]) return;
						const idStr = segId != null ? String(segId) : '';
						const hitRec = hierarchy.byId[idStr];
						const hitInfo = hitRec ? 'FOUND — level:"' + hitRec.level + '" parentId:"' + hitRec.parentId + '"' : 'NOT FOUND in hierarchy map';
						const key = 'id:"' + segId + '" → ' + hitInfo + ' | chain: Sector="' + chain.Sector + '" Project="' + chain.Project + '" Clinic="' + chain.Clinic + '" | trace: ' + (chain._trace || '(none)');
						unmatchedStreamline[key] = (unmatchedStreamline[key] || 0) + 1;
				  };

			const resolvedRows = buildResolvedRows(rows, hierarchy, chainCache, f, debugCollector);

			resolvedRows.forEach(({colValue, chain}) => {
				columnSet.add(colValue);
				if (!columnChains[colValue]) columnChains[colValue] = chain;
			});

			const segments = [...columnSet].sort((a, b) => {
				if (a === 'Unclassified') return 1;
				if (b === 'Unclassified') return -1;
				const ca = columnChains[a] || {};
				const cb = columnChains[b] || {};
				const sa = ca.Sector || '';
				const sb = cb.Sector || '';
				if (sa !== sb) return sa.localeCompare(sb);
				const pa = ca.Project || '';
				const pb = cb.Project || '';
				if (pa !== pb) return pa.localeCompare(pb);
				return a.localeCompare(b);
			});

			/* Entity ids -> {name, url}, resolved once for the whole report. */
			const entityLookup = resolveEntities([...new Set(resolvedRows.map(r => r.row.values[COL.ENTITY]).filter(v => v != null && v !== ''))].map(String));

			/* ── Pivot, and in the same pass collect the drill-down payload ──
			 * Strings are interned into `pool` so repeated customer names, document numbers and
			 * column labels cost one entry each instead of one per line. */
			const pivot = {};
			const acctSortKey = {};
			const unmatchedTypes = {};

			const pool = [];
			const poolIdx = {};
			const intern = v => {
				const s = v == null ? '' : String(v);
				if (poolIdx[s] === undefined) {
					poolIdx[s] = pool.length;
					pool.push(s);
				}
				return poolIdx[s];
			};

			/* Entities are their own little table of [name, url] pairs referenced by index, so a
			 * customer that appears on 70 lines costs one entry. -1 on a line means "no entity". */
			const entityDescs = [];
			const entityDescIdx = {};
			const internEntity = rawEntity => {
				if (rawEntity == null || rawEntity === '') return -1;
				const key = String(rawEntity);
				if (entityDescIdx[key] === undefined) {
					const info = entityLookup.map[key];
					entityDescIdx[key] = entityDescs.length;
					entityDescs.push([info ? info.name : key, info ? info.url : '']);
				}
				return entityDescIdx[key];
			};

			const drillLines = []; // [dateKey, acctIdx, colIdx, secIdx, typeIdx, docIdx, entityIdx, tranIdIdx, amount]
			const cellLineCount = {}; // "acctIdx|colIdx|secIdx" -> lines behind that cell
			const rowLineCount = {}; // "acctIdx|secIdx"         -> lines behind that account's row Total
			let sawTranIds = false;

			const secIdxOf = {};
			SECTIONS.filter(s => !s.virtual).forEach(s => {
				pivot[s.key] = {};
				secIdxOf[s.key] = intern(s.key);
			});

			resolvedRows.forEach(({row, colValue}) => {
				const accountId = row.values[COL.ACCOUNT];
				const netAmount = Number(row.values[COL.NETAMOUNT]) || 0;
				const dsType = String(row.values[COL.ACCOUNTTYPE] || '');
				const acct = accountMap[accountId];
				if (!acct) return;

				const sectionKey = sectionOfRow(row, acct);

				if (!sectionKey) {
					const combo = `dataset:"${dsType}" | acctDisplay:"${acct.typeDisplay}"`;
					unmatchedTypes[combo] = (unmatchedTypes[combo] || 0) + 1;
					return;
				}

				const section = SECTION_BY_KEY[sectionKey];
				const amount = section.signFlip ? -netAmount : netAmount;

				const acctNum = acct.number || '';
				const acctLabel = accountLabelOf(acct, accountId);

				if (!acctSortKey[acctLabel]) acctSortKey[acctLabel] = parseInt(acctNum.replace(/\D/g, ''), 10) || 0;

				if (!pivot[sectionKey][acctLabel]) pivot[sectionKey][acctLabel] = {};
				if (!pivot[sectionKey][acctLabel][colValue]) pivot[sectionKey][acctLabel][colValue] = 0;
				pivot[sectionKey][acctLabel][colValue] += amount;

				/* Same line, kept for the drill-down. Matching is by account LABEL index, which is
				 * exactly what the pivot rows are keyed by, so a cell and its detail can't disagree. */
				const aIdx = intern(acctLabel);
				const cIdx = intern(colValue);
				const xIdx = secIdxOf[sectionKey];
				const rawType = row.values[COL.TYPE];
				const tranId = row.values[COL.TRANID];
				if (tranId) sawTranIds = true;

				drillLines.push([
					parseDMY(row.values[COL.TRANDATE]) || 0,
					aIdx,
					cIdx,
					xIdx,
					intern(TRAN_TYPE_LABELS[rawType] || rawType || ''),
					intern(row.values[COL.DISPLAYNAME] || ''),
					internEntity(row.values[COL.ENTITY]),
					tranId ? intern(String(tranId)) : -1,
					amount
				]);

				const cellKey = aIdx + '|' + cIdx + '|' + xIdx;
				cellLineCount[cellKey] = (cellLineCount[cellKey] || 0) + 1;
				const rowKey = aIdx + '|' + xIdx;
				rowLineCount[rowKey] = (rowLineCount[rowKey] || 0) + 1;
			});

			const drillEnabled = drillLines.length > 0 && drillLines.length <= DRILL_MAX_EMBED;

			/* ── Section totals ── */
			const totals = {};
			SECTIONS.filter(s => !s.virtual).forEach(s => {
				totals[s.key] = {};
				segments.forEach(seg => {
					totals[s.key][seg] = Object.values(pivot[s.key]).reduce((sum, m) => sum + (m[seg] || 0), 0);
				});
			});

			['gross', 'operating', 'net'].forEach(k => {
				totals[k] = {};
			});
			segments.forEach(seg => {
				totals['gross'][seg] = (totals['income'][seg] || 0) - (totals['cogs'][seg] || 0);
				totals['operating'][seg] = (totals['gross'][seg] || 0) - (totals['expense'][seg] || 0);
				totals['net'][seg] = (totals['operating'][seg] || 0) + (totals['othincome'][seg] || 0) - (totals['othexpense'][seg] || 0);
			});

			const rowSum = m => segments.reduce((s, seg) => s + (m[seg] || 0), 0);
			const secTotal = key => segments.reduce((s, seg) => s + (totals[key][seg] || 0), 0);

			/* ── HTML ── */
			const colCount = segments.length + 2;

			let html = `
<style>
  .pnl-outer { font-family: Arial, sans-serif; font-size: 12px; position: relative; }
  .pnl-meta { color:#555; margin-bottom:8px; font-size:11px; }
  .pnl-breadcrumb {
    background:#1e4d91; color:#fff; padding:6px 10px; font-weight:bold;
    font-size:12px; margin-bottom:6px; border-radius:3px;
  }
  .pnl-scroll { width: 100%; max-width: 100%; overflow-x: auto; overflow-y: auto; max-height: calc(100vh - 260px); }
  .pnl-table { border-collapse: separate; border-spacing: 0; width: max-content; min-width: 100%; table-layout: auto; }
  .pnl-table th, .pnl-table td { border: 1px solid #d0d0d0; padding: 4px 8px; white-space: nowrap; }
  .pnl-table thead th { position: sticky; top: 0; z-index: 10; background: #1e4d91; color: #fff; text-align: center; border-color: #14367a; font-size: 13px; font-weight: bold; }
  .pnl-table thead th.col-acct  { text-align: left; min-width: 300px; }
  .pnl-table thead th.col-num   { min-width: 130px; }
  .pnl-table thead th.col-total { background: #0d2d5e; border-left: 2px solid #ccc !important; min-width: 140px; }
  .pnl-table td.col-acct { position: sticky; left: 0; z-index: 8; background: #ffffff !important; color: #222 !important; min-width: 300px; border-right: 2px solid #d0d0d0; box-shadow: 2px 0 4px rgba(0,0,0,0.1); }
  .pnl-table th.col-acct { position: sticky; left: 0; top: 0; z-index: 30; background: #1e4d91 !important; color: #ffffff !important; min-width: 300px; }
  .col-num   { text-align: right; }
  .col-total { text-align: right; border-left: 2px solid #1e4d91 !important; font-weight: bold; }
  tr.sec-head td { background: #d6e4f7; font-weight: bold; color: #1e4d91; border-top: 2px solid #1e4d91; text-transform: uppercase; letter-spacing: .4px; font-size: 11px; }
  tr.acct-row td           { background: #fff; }
  tr.acct-row:hover td     { background: #f0f6ff; }
  tr.acct-row td.col-acct  { padding-left: 24px; color: #222; }
  tr.sec-total td { background: #eaf0fb; font-weight: bold; border-top: 1px solid #a8c4e8; border-bottom: 2px solid #1e4d91; color: #1e4d91; }
  tr.subtotal td { background: #1e4d91; color: #fff; font-weight: bold; border-top: 2px solid #14367a; border-bottom: 2px solid #14367a; }
  tr.subtotal td.col-total { background: #14367a; }
  tr.net-total td { background: #0d2d5e; color: #fff; font-weight: bold; font-size: 13px; border-top: 3px solid #0a2044; border-bottom: 3px solid #0a2044; }
  tr.net-total td.col-total { background: #091b3a; }
  .neg { color: #c0392b; }
  tr.subtotal .neg, tr.net-total .neg { color: #ff9999; }
  tr.sec-total .neg { color: #c0392b; }

  /* Drill affordance: amounts stay plain until the row is approached. */
  a.pnl-drill-link { color: inherit; text-decoration: none; border-bottom: 1px dotted transparent; cursor: pointer; }
  a.pnl-drill-link:hover { color: #1e4d91; border-bottom-color: #1e4d91; }
  tr.acct-row:hover a.pnl-drill-link { border-bottom-color: #b9cdea; }
  a.pnl-drill-link:focus-visible { outline: 2px solid #1e4d91; outline-offset: 1px; }

  /* Modal */
  .pnl-dd-overlay { display: none; position: fixed; inset: 0; z-index: 10000; background: rgba(10,32,68,.45); padding: 40px 24px; align-items: flex-start; justify-content: center; }
  .pnl-dd-overlay.open { display: flex; }
  .pnl-dd-modal { background:#fff; border-radius:4px; box-shadow:0 18px 48px rgba(0,0,0,.35); width:min(1100px,100%); max-height:calc(100vh - 80px); display:flex; flex-direction:column; position:relative; animation: pnlDdIn .16s ease-out; }
  @keyframes pnlDdIn { from { opacity:0; transform: translateY(-8px); } to { opacity:1; transform:none; } }
  @media (prefers-reduced-motion: reduce) { .pnl-dd-modal { animation: none; } }
  .pnl-dd-close { position:absolute; top:8px; right:10px; z-index:5; background:transparent; border:0; color:#fff; font-size:22px; line-height:1; cursor:pointer; padding:2px 6px; border-radius:3px; }
  .pnl-dd-close:hover { background: rgba(255,255,255,.18); }

  .pnl-dd { font-family: Arial, sans-serif; font-size:12px; color:#222; display:flex; flex-direction:column; min-height:0; }
  .pnl-dd .dd-head { background:#1e4d91; color:#fff; padding:10px 40px 10px 14px; border-radius:4px 4px 0 0; }
  .pnl-dd .dd-title { font-size:14px; font-weight:bold; }
  .pnl-dd .dd-sub { font-size:11px; opacity:.85; margin-top:3px; }
  .pnl-dd .dd-bar { display:flex; align-items:center; gap:10px; padding:6px 14px; background:#f4f7fc; border-bottom:1px solid #d9e2f0; font-size:11px; color:#44506a; }
  .pnl-dd .dd-bar label { display:flex; align-items:center; gap:5px; cursor:pointer; }
  .pnl-dd .dd-bar .dd-count { margin-left:auto; color:#6b7690; }
  .pnl-dd .dd-scroll { overflow:auto; min-height:0; }
  .pnl-dd table { border-collapse:separate; border-spacing:0; width:100%; }
  .pnl-dd th, .pnl-dd td { border-bottom:1px solid #e4e4e4; padding:5px 10px; white-space:nowrap; text-align:left; }
  .pnl-dd thead th { position:sticky; top:0; z-index:2; background:#eaf0fb; color:#1e4d91; font-weight:bold; border-bottom:2px solid #1e4d91; }
  .pnl-dd td.num, .pnl-dd th.num { text-align:right; }
  .pnl-dd tbody tr:nth-child(even) td { background:#fafbfd; }
  .pnl-dd tbody tr:hover td { background:#f0f6ff; }
  .pnl-dd .dd-foot { background:#1e4d91; color:#fff; font-weight:bold; padding:7px 14px; display:flex; justify-content:space-between; border-radius:0 0 4px 4px; }
  .pnl-dd .neg { color:#c0392b; }
  .pnl-dd .dd-foot .neg { color:#ff9999; }
  .pnl-dd .dd-empty { padding:24px; text-align:center; color:#777; }
  .pnl-dd .dd-note { background:#fff3cd; border-bottom:1px solid #ffc107; padding:6px 14px; font-size:11px; }
  .pnl-dd a.tranlink { color:#1e4d91; text-decoration:none; border-bottom:1px dotted #1e4d91; }
  .pnl-dd a.tranlink:hover { border-bottom-style:solid; }
</style>

<div class="pnl-outer">`;

			/* Breadcrumb */
			const crumbs = [];
			crumbs.push('Level: ' + esc(levelRaw));
			if (sectorFilterRaw) crumbs.push('Sector: ' + esc(sectorFilterRaw));
			if (projectFilterRaw) crumbs.push('Project: ' + esc(projectFilterRaw));
			if (clinicFilterRaw) crumbs.push('Clinic: ' + esc(clinicFilterRaw));
			if (groupingFilterRaw) crumbs.push('Grouping: ' + esc(groupingOptions[groupingFilterRaw] || groupingFilterRaw));
			html += '<div class="pnl-breadcrumb">' + crumbs.join(' &nbsp;&raquo;&nbsp; ') + '</div>';

			html += '<p class="pnl-meta"><b>' + (segments.length + 2).toLocaleString() + '</b> Total Columns Displayed';
			if (drillEnabled) {
				html += ' &nbsp;·&nbsp; ' + drillLines.length.toLocaleString() + ' posting lines loaded — click any amount to see the transactions behind it';
			} else if (drillLines.length > DRILL_MAX_EMBED) {
				html += ' &nbsp;·&nbsp; <b>drill-down off:</b> ' + drillLines.length.toLocaleString() + ' posting lines exceeds the ' + DRILL_MAX_EMBED.toLocaleString() + '-line limit. Narrow the period or segment filters to re-enable it.';
			}
			html += '</p>';

			if (entityLookup.error) {
				html += '<div style="background:#fff3cd;border:1px solid #ffc107;padding:8px;margin-bottom:10px;font-size:11px;">';
				html += '<b>&#9888; Entity names could not be resolved</b> — the drill-down will show internal IDs instead of customer/vendor names.<br>';
				html += esc(entityLookup.error);
				html += '</div>';
			}

			if (Object.keys(unmatchedTypes).length > 0) {
				html += '<div style="background:#fff3cd;border:1px solid #ffc107;padding:8px;margin-bottom:10px;font-size:11px;">';
				html += '<b>&#9888; Unmatched account types (these rows were skipped):</b><br>';
				Object.entries(unmatchedTypes).forEach(([k, count]) => {
					html += esc(k) + ' — <b>' + count + ' rows</b><br>';
				});
				html += '</div>';
			}

			if (debugMode) {
				html += '<div style="background:#e7f3ff;border:1px solid #1e4d91;padding:8px;margin-bottom:10px;font-size:11px;">';
				html += '<b>Sample of loaded hierarchy names (' + Object.keys(hierarchy.byName).length + ' total records loaded from ' + esc(SEGMENT_RECTYPE) + '):</b><br>';
				Object.keys(hierarchy.byName)
					.slice(0, 15)
					.forEach(n => {
						const id = hierarchy.byName[n];
						const rec = hierarchy.byId[id];
						html += esc(n) + ' &rarr; level(resolved): "' + esc(rec.level) + '" | getText: "' + esc(rec._debugLevelText) + '" | getValue: "' + esc(rec._debugLevelValue) + '" | parentId: ' + esc(rec.parentId || '(none)') + '<br>';
					});
				html += '</div>';

				if (Object.keys(unmatchedStreamline).length > 0) {
					html += '<div style="background:#fff3cd;border:1px solid #ffc107;padding:8px;margin-bottom:10px;font-size:11px;">';
					html += '<b>&#9888; Unmatched Business Streamline values (dataset col 9/10 did not resolve to any hierarchy record):</b><br>';
					Object.entries(unmatchedStreamline).forEach(([k, count]) => {
						html += esc(k) + ' — <b>' + count + ' rows</b><br>';
					});
					html += '</div>';
				}
			}

			/* ── Multi-row header: parent levels group above the chosen leaf level ── */
			const totalHeaderRows = levelRaw === 'Sector' ? 1 : levelRaw === 'Project' ? 2 : 3;
			const headerRowDefs = [];
			if (levelRaw === 'Project' || levelRaw === 'Clinic') {
				headerRowDefs.push({
					keyFn: seg => (columnChains[seg] || {}).Sector || '',
					displayFn: keyVal => keyVal
				});
			}
			if (levelRaw === 'Clinic') {
				headerRowDefs.push({
					keyFn: seg => ((columnChains[seg] || {}).Sector || '') + '|' + ((columnChains[seg] || {}).Project || ''),
					displayFn: keyVal => keyVal.split('|')[1] || ''
				});
			}
			headerRowDefs.push({
				keyFn: seg => seg,
				displayFn: (keyVal, seg) => seg
			});

			html += '<div class="pnl-scroll"><table class="pnl-table"><thead>';
			headerRowDefs.forEach((rowDef, idx) => {
				html += '<tr>';
				if (idx === 0) html += `<th class="col-acct" rowspan="${totalHeaderRows}">Account</th>`;
				let i = 0;
				while (i < segments.length) {
					const seg = segments[i];
					const keyVal = rowDef.keyFn(seg);
					let span = 1;
					while (i + span < segments.length && rowDef.keyFn(segments[i + span]) === keyVal) span++;
					let displayText = rowDef.displayFn(keyVal, seg);
					if (!displayText) displayText = seg === 'Unclassified' ? 'Unclassified' : '';
					html += `<th class="col-num" colspan="${span}" title="${esc(displayText)}">${esc(displayText)}</th>`;
					i += span;
				}
				if (idx === 0) html += `<th class="col-total" rowspan="${totalHeaderRows}">Total</th>`;
				html += '</tr>';
			});
			html += '</thead><tbody>';

			const numCell = (v, cls) => {
				const neg = v < 0;
				return `<td class="${cls || 'col-num'}${neg ? ' neg' : ''}">${esc(fmt(v))}</td>`;
			};

			/**
			 * Number that opens the drill-down. Linked whenever posting lines exist behind it — a cell
			 * showing "-" because +50 and -50 cancel out still has two transactions worth seeing.
			 * `colIdx` of -1 means "every column", used by the account's row Total.
			 */
			const numCellDrill = (v, cls, acctIdx, colIdx, secIdx, lineCount) => {
				if (!drillEnabled || !lineCount) return numCell(v, cls);
				const neg = v < 0;
				return (
					`<td class="${cls || 'col-num'}${neg ? ' neg' : ''}">` +
					`<a class="pnl-drill-link" href="javascript:void(0);" role="button"` +
					` title="${lineCount} transaction line${lineCount === 1 ? '' : 's'}"` +
					` onclick="pnlDrill(${acctIdx},${colIdx},${secIdx});return false;">${esc(fmt(v))}</a></td>`
				);
			};

			SECTIONS.forEach(sec => {
				if (sec.virtual) {
					const isNet = sec.key === 'net';
					const cls = isNet ? 'net-total' : 'subtotal';
					html += `<tr class="${cls}"><td class="col-acct">${esc(sec.label)}</td>`;
					let total = 0;
					segments.forEach(seg => {
						const v = totals[sec.key][seg] || 0;
						total += v;
						html += numCell(v);
					});
					html += numCell(total, 'col-total');
					html += '</tr>';
					return;
				}

				html += `<tr class="sec-head"><td colspan="${colCount}">${esc(sec.label)}</td></tr>`;

				const acctLabels = Object.keys(pivot[sec.key]).sort((a, b) => (acctSortKey[a] || 0) - (acctSortKey[b] || 0));

				if (acctLabels.length === 0) {
					html += `<tr class="acct-row"><td class="col-acct" style="color:#aaa;padding-left:24px;">—</td>`;
					segments.forEach(() => {
						html += '<td class="col-num">-</td>';
					});
					html += '<td class="col-total">-</td></tr>';
				} else {
					const secIdx = secIdxOf[sec.key];
					acctLabels.forEach(lbl => {
						const aIdx = poolIdx[lbl];
						html += '<tr class="acct-row">';
						html += `<td class="col-acct">${esc(lbl)}</td>`;
						const rt = rowSum(pivot[sec.key][lbl]);
						segments.forEach(seg => {
							const cIdx = poolIdx[seg];
							html += numCellDrill(pivot[sec.key][lbl][seg] || 0, 'col-num', aIdx, cIdx, secIdx, cellLineCount[aIdx + '|' + cIdx + '|' + secIdx] || 0);
						});
						html += numCellDrill(rt, 'col-total', aIdx, -1, secIdx, rowLineCount[aIdx + '|' + secIdx] || 0);
						html += '</tr>';
					});
				}

				const st = secTotal(sec.key);
				html += `<tr class="sec-total"><td class="col-acct">Total ${esc(sec.label)}</td>`;
				segments.forEach(seg => {
					html += numCell(totals[sec.key][seg] || 0);
				});
				html += numCell(st, 'col-total');
				html += '</tr>';
			});

			html += '</tbody></table></div>';

			/* ── Drill-down: payload + modal + renderer ── */
			if (drillEnabled) {
				/* Context line shown under the modal title. */
				const pMap = periodNames([f.fromPeriodId, f.toPeriodId]);
				const ddCtx = [];
				if (f.fromPeriodId || f.toPeriodId) {
					ddCtx.push('Periods: ' + (f.fromPeriodId ? pMap[f.fromPeriodId] || f.fromPeriodId : 'start') + ' → ' + (f.toPeriodId ? pMap[f.toPeriodId] || f.toPeriodId : 'end'));
				}
				if (f.fromDateRaw || f.toDateRaw) ddCtx.push('Dates: ' + (f.fromDateRaw || 'start') + ' → ' + (f.toDateRaw || 'end'));
				if (sectorFilterRaw) ddCtx.push('Sector: ' + sectorFilterRaw);
				if (projectFilterRaw) ddCtx.push('Project: ' + projectFilterRaw);
				if (clinicFilterRaw) ddCtx.push('Clinic: ' + clinicFilterRaw);
				if (groupingFilterRaw) ddCtx.push('Grouping: ' + (groupingOptions[groupingFilterRaw] || groupingFilterRaw));

				const payload = {lv: levelRaw, ctx: ddCtx.join(' » '), s: pool, e: entityDescs, r: drillLines, tid: sawTranIds};
				const payloadJson = JSON.stringify(payload).replace(/</g, '\\u003c');

				html += `
<div id="pnl-dd-overlay" class="pnl-dd-overlay" aria-hidden="true">
  <div class="pnl-dd-modal" role="dialog" aria-modal="true" aria-label="Transaction detail">
    <button type="button" class="pnl-dd-close" aria-label="Close detail" onclick="pnlDrillClose();">&times;</button>
    <div id="pnl-dd-body" class="pnl-dd"></div>
  </div>
</div>
</div>
<script type="text/javascript">
(function () {
  var D = ${payloadJson};
  var state = null;      // {a, c, x} of the open cell
  var groupTx = true;    // roll a transaction's GL lines into one row
  var hideZeros = true;
  var lastTrigger = null;

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* Mirrors the server's fmt(): "-" for zero, parentheses for negatives. */
  function fmt(v) {
    v = Number(v || 0);
    if (v === 0) return '-';
    var abs = Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    return v < 0 ? '(' + abs + ')' : abs;
  }

  /* Date key 20260123 -> 23/01/2026 */
  function fmtDate(k) {
    if (!k) return '';
    var s = String(k);
    return s.slice(6, 8) + '/' + s.slice(4, 6) + '/' + s.slice(0, 4);
  }

  function overlay() { return document.getElementById('pnl-dd-overlay'); }
  function body()    { return document.getElementById('pnl-dd-body'); }

  function render() {
    var bd = body();
    if (!bd || !state) return;

    var all = D.r.filter(function (r) {
      return r[1] === state.a && r[3] === state.x && (state.c < 0 || r[2] === state.c);
    });

    var total = 0;
    all.forEach(function (r) { total += r[8]; });

    var showCol = state.c < 0;

    /* One row per transaction — keyed per column as well, so an allocation journal that debits
     * one clinic and credits another still shows both legs instead of cancelling itself out. */
    var rows;
    if (groupTx) {
      var byKey = {}, order = [];
      all.forEach(function (r) {
        var k = (r[7] >= 0 ? 't' + r[7] : 'd' + r[5]) + '|' + r[2];
        var g = byKey[k];
        if (!g) {
          g = byKey[k] = {k: r[0], ty: r[4], doc: r[5], ent: r[6], tid: r[7], col: r[2], amt: 0};
          order.push(g);
        }
        if (r[0] && (!g.k || r[0] < g.k)) g.k = r[0];
        g.amt += r[8];
      });
      rows = order;
    } else {
      rows = all.map(function (r) {
        return {k: r[0], ty: r[4], doc: r[5], ent: r[6], tid: r[7], col: r[2], amt: r[8]};
      });
    }
    rows.sort(function (p, q) { return p.k - q.k || D.s[p.doc].localeCompare(D.s[q.doc]); });

    var zeroCount = 0;
    rows.forEach(function (r) { if (!r.amt) zeroCount++; });
    var shown = hideZeros ? rows.filter(function (r) { return !!r.amt; }) : rows;
    var unit = groupTx ? 'transaction' : 'line';

    var h = '<div class="dd-head">' +
      '<div class="dd-title">' + esc(D.s[state.a]) + '</div>' +
      '<div class="dd-sub">' + esc(D.lv) + ': ' + esc(state.c < 0 ? 'All ' + D.lv + 's' : D.s[state.c]) +
      (D.ctx ? ' &nbsp;&raquo;&nbsp; ' + esc(D.ctx) : '') + '</div></div>';

    h += '<div class="dd-bar">';
    h += '<label><input type="checkbox" id="pnl-dd-group"' + (groupTx ? ' checked' : '') + '> Group by transaction</label>';
    if (zeroCount) {
      h += '<label><input type="checkbox" id="pnl-dd-zeros"' + (hideZeros ? ' checked' : '') + '> ' +
           'Hide ' + zeroCount.toLocaleString() + ' zero-amount ' + unit + (zeroCount === 1 ? '' : 's') + '</label>';
    }
    h += '<span class="dd-count">' + all.length.toLocaleString() + ' GL line' + (all.length === 1 ? '' : 's') + '</span>';
    h += '</div>';

    if (!shown.length) {
      h += '<div class="dd-empty">No lines to show.</div>';
    } else {
      h += '<div class="dd-scroll"><table><thead><tr>' +
           '<th>Date</th><th>Type</th><th>Document</th><th>Name</th>' +
           (showCol ? '<th>' + esc(D.lv) + '</th>' : '') +
           '<th class="num">Amount</th></tr></thead><tbody>';

      shown.forEach(function (r) {
        var doc = esc(D.s[r.doc]);
        if (r.tid >= 0) {
          /* transaction.nl?id= redirects to the right record page for any transaction type. */
          doc = '<a class="tranlink" target="_blank" rel="noopener" href="/app/accounting/transactions/transaction.nl?id=' +
                encodeURIComponent(D.s[r.tid]) + '">' + doc + '</a>';
        }

        var ent = '';
        if (r.ent >= 0) {
          var e = D.e[r.ent];
          ent = esc(e[0]);
          if (e[1]) ent = '<a class="tranlink" target="_blank" rel="noopener" href="' + esc(e[1]) + '">' + ent + '</a>';
        }

        h += '<tr><td>' + esc(fmtDate(r.k)) + '</td>' +
             '<td>' + esc(D.s[r.ty]) + '</td>' +
             '<td>' + doc + '</td>' +
             '<td>' + ent + '</td>' +
             (showCol ? '<td>' + esc(D.s[r.col]) + '</td>' : '') +
             '<td class="num' + (r.amt < 0 ? ' neg' : '') + '">' + esc(fmt(r.amt)) + '</td></tr>';
      });

      h += '</tbody></table></div>';
    }

    h += '<div class="dd-foot"><span>' + shown.length.toLocaleString() +
         (shown.length === rows.length ? '' : ' of ' + rows.length.toLocaleString()) +
         ' ' + unit + (rows.length === 1 ? '' : 's') + '</span>' +
         '<span>Total &nbsp;<span class="' + (total < 0 ? 'neg' : '') + '">' + esc(fmt(total)) + '</span></span></div>';

    if (!D.tid) {
      h += '<div class="dd-note">Add the transaction <b>id</b> column to the dataset to turn each document into a link.</div>';
    }

    bd.innerHTML = h;

    var gb = document.getElementById('pnl-dd-group');
    if (gb) gb.onchange = function () { groupTx = gb.checked; render(); };
    var zb = document.getElementById('pnl-dd-zeros');
    if (zb) zb.onchange = function () { hideZeros = zb.checked; render(); };
  }

  window.pnlDrill = function (a, c, x) {
    var ov = overlay();
    if (!ov) return;
    lastTrigger = document.activeElement;
    state = {a: a, c: c, x: x};
    ov.className = 'pnl-dd-overlay open';
    ov.setAttribute('aria-hidden', 'false');
    render();
    var closeBtn = ov.querySelector('.pnl-dd-close');
    if (closeBtn) closeBtn.focus();
  };

  window.pnlDrillClose = function () {
    var ov = overlay();
    if (!ov) return;
    ov.className = 'pnl-dd-overlay';
    ov.setAttribute('aria-hidden', 'true');
    if (body()) body().innerHTML = '';
    state = null;
    groupTx = true;
    hideZeros = true;
    if (lastTrigger && lastTrigger.focus) lastTrigger.focus();
    lastTrigger = null;
  };

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' || e.keyCode === 27) window.pnlDrillClose();
  });
  document.addEventListener('click', function (e) {
    if (e.target === overlay()) window.pnlDrillClose();
  });
})();
</script>`;
			} else {
				html += '</div>';
			}

			fHtml.defaultValue = html;
		} catch (e) {
			fHtml.defaultValue = '<div style="color:red;font-family:Arial;padding:12px;">' + '<b>' + esc(e.name) + '</b><br>' + esc(e.message) + '<br><pre style="font-size:11px">' + esc(e.stack || '') + '</pre></div>';
		}

		context.response.writePage(form);
	};

	return {onRequest};
});
