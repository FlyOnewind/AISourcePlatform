"""种子数据脚本：建表 + 灌入完整业务数据。

包含：
- 7个业务Agent + master_agent
- 6个完整知识库（含丰富文档）
- 8个实用Skill（含完整Prompt模板）
- 6个Prompt模板
- 3个工具
- 完整的权限配置
- 完整的策略配置

用法: uv run python -m app.seeds.seed_data
幂等：重复运行会跳过已存在的key，不会重复插入或报错。
"""
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, create_all_tables
from app.core.security import generate_api_key
from app.models.agent import AdminUser, Agent
from app.models.capability import Capability, CapabilityVersion
from app.models.capability_permission import CapabilityPermission
from app.models.knowledge import Document, KnowledgeBase
from app.models.policy import Policy
from app.models.skill import PromptTemplate, Skill
from app.services.knowledge_service import KnowledgeService
from app.services.llm.factory import get_llm_provider
from app.services.tools import ToolRegistry

# ==========================================
# Agent定义
# ==========================================
BUSINESS_AGENTS = [
    (
        "hr_agent_001",
        "人事智能体",
        "hr_agent",
        "hr",
        "人事部",
        "负责员工入职、培训、绩效评估、考勤管理等人事管理任务",
    ),
    (
        "finance_agent_001",
        "财务智能体",
        "finance_agent",
        "finance",
        "财务部",
        "负责预算管理、ROI测算、费用报销审核、财务报表生成等财务任务",
    ),
    (
        "product_submission_agent_001",
        "团品提报智能体",
        "product_submission_agent",
        "product",
        "商品部",
        "负责团品审核、商品信息录入、供应商管理、价格策略制定",
    ),
    (
        "supply_chain_agent_001",
        "供应链智能体",
        "supply_chain_agent",
        "supply_chain",
        "供应链部",
        "负责库存管理、物流跟踪、供应链协同、供应商评价",
    ),
    (
        "merchant_agent_001",
        "招扶商智能体",
        "merchant_agent",
        "merchant",
        "招商部",
        "负责招商谈判、门店管理、加盟商支持、合同管理",
    ),
    (
        "operation_agent_001",
        "运营智能体",
        "operation_agent",
        "operation",
        "运营部",
        "负责直播运营、活动策划、用户增长、数据分析",
    ),
    (
        "business_school_agent_001",
        "商学院智能体",
        "business_school_agent",
        "business_school",
        "商学院",
        "负责培训课程设计、素材制作、培训效果评估",
    ),
]

# ==========================================
# 知识库文档内容（大幅扩充）
# ==========================================
DOCS = {
    "kb_store_operation": [
        (
            "门店直播运营SOP完整版.md",
            """# 门店直播运营SOP（完整版）

## 1. 开播前准备

### 1.1 货品检查清单
- [ ] 货品盘点完成，实物与库存系统一致
- [ ] 价格核对确认，标签价格与系统价格一致
- [ ] 库存确认充足，预估销量不超过可用库存
- [ ] 样品准备充分，展示用商品状态良好
- [ ] 赠品准备到位，配套物品齐全
- [ ] 商品资质文件完整，符合平台要求

### 1.2 设备检查清单
- [ ] 主摄像头正常，画面清晰，角度合适
- [ ] 副摄像头正常，多机位准备到位
- [ ] 麦克风收音测试正常，无杂音
- [ ] 灯光布置合理，主光、辅光、轮廓光均正常
- [ ] 网络带宽测试达标，上行不低于10Mbps
- [ ] 直播推流软件配置完成，画面码率、帧率设置正确
- [ ] 备用网络准备到位（4G/5G备用方案）
- [ ] 备用电源/充电宝准备
- [ ] 直播账号登录状态检查，权限确认
- [ ] 直播间标题、封面、标签设置完成

### 1.3 人员准备
- [ ] 主播到场，状态良好
- [ ] 助播/运营人员到位
- [ ] 客服人员在线
- [ ] 发货协调人确认待命
- [ ] 应急联系人确认

### 1.4 脚本与合规准备
- [ ] 直播脚本撰写完成并审核通过
- [ ] 违禁词检测已完成，无违规内容
- [ ] 营销话术符合广告法要求
- [ ] 价格表述准确，无虚假承诺
- [ ] 售后政策清晰明确
- [ ] 直播流程与时间节点确认无误

## 2. 直播流程规范

### 2.1 开场阶段（前5-10分钟）
- 欢迎语设计：亲切自然，有记忆点
- 直播间介绍：主播身份、直播主题、福利预告
- 互动引导：引导用户点赞、关注、分享
- 暖场活动：简单的互动小游戏或问答

### 2.2 产品讲解阶段
- 产品展示顺序规划：爆品在前，利润品在后
- 单品讲解时长控制：单品讲解5-8分钟为宜
- 讲解结构：FABE法则（特征、优势、利益、证据）
- 现场演示：真实使用场景展示
- 价格权益披露：清晰明确，无隐藏消费
- 限时限量引导：营造稀缺感但不虚假

### 2.3 互动转化阶段
- 问题回答及时：不超过30秒响应
- 负面评论处理：不回避，正面回应
- 逼单话术合理：不强行推销，以价值引导为主
- 订单确认引导：引导用户确认地址、规格

### 2.4 收官阶段
- 直播总结回顾
- 未购用户引导：关注下次直播
- 已购用户感谢与服务承诺
- 下期直播预告
- 结束话术设计

## 3. 到店引流策略

### 3.1 线上引流方法
- 直播预告发布：提前3-7天发布预告
- 优惠券发放：直播专属到店优惠券
- 社群裂变：邀请好友进群获得奖励
- 短视频预热：提前发布产品相关短视频
- 同城定位：确保直播间地理位置准确

### 3.2 会员运营策略
- 会员分层：普通会员/VIP会员的区别权益
- 专属优惠：会员专属价、积分倍数等
- 复购激励：满返、满赠活动设计
- 到店频次提升：周期活动提醒
- 生日/节日关怀：个性化触达

## 4. 直播后复盘

### 4.1 数据指标分析
- 观看人数：最高在线、平均在线、累计观看
- 互动指标：评论数、点赞数、分享数、新增关注数
- 转化指标：订单数、GMV、客单价、转化率
- 观看时长：平均观看时长、跳出率分析

### 4.2 问题总结
- 直播中出现的技术问题
- 产品讲解的不足
- 客服响应问题
- 物流发货预期管理

### 4.3 改进计划
- 问题根因分析
- 改进措施制定
- 责任人与时间节点
- 下次直播验证计划
""",
        ),
        (
            "直播话术模板库.md",
            """# 直播话术模板库

## 通用开场话术

### 标准开场
"哈喽，直播间的家人们大家好！欢迎来到今天的直播间！我是你们的主播XX。今天为大家带来了超多惊喜好物，赶紧先点点关注不迷路！"

### 互动引导开场
"欢迎新进直播间的家人们！新来的朋友们，左上角的关注点一点，点赞帮主播戳一戳，今天点赞到一万给大家抽免单福利哦！"

## 产品介绍话术

### FABE结构话术
"这款产品采用了[材质/技术]，这是它的特点；它可以[具体功能]，这是它的优势；用了它之后你可以[给用户带来的好处]，这是它的利益点；而且已经有[具体数据/案例]，这就是最好的证明！"

### 场景化话术
"想象一下，当你[具体场景]时，有了这款产品，你就可以[解决的问题]，是不是特别方便？"

## 逼单转化话术

### 稀缺感营造话术
"这款产品的库存真的不多了，今天直播间的价格仅限本场直播，过了今天就恢复原价。喜欢的家人们千万不要犹豫，犹豫就会白给，徘徊就会错过！"

### 信任建立话术
"大家完全可以放心下单，我们是品牌官方直播间，正品保障，假一赔三，七天无理由退换，还送运费险。购物零风险，放心大胆拍！"

## 互动问答话术

### 价格相关问答
"有家人问为什么这么便宜？因为今天是我们的品牌日，拿出了诚意来回馈粉丝，这个价格平时真的没有，错过今天再等一年！"

### 质量相关问答
"关于质量问题大家完全不用担心，我们都是经过严格质检的，而且有任何质量问题，随时联系客服退换，我们承担运费！"

## 违禁词自查清单

### 绝对化用语（禁用）
- 最、第一、顶级、极致
- 永久、万能、包治百病
- 国家级、世界级、最高级
- 100%有效、绝对安全

### 虚假承诺（禁用）
- 无效退款、包治百病
- 稳赚不赔、一夜暴富
- 马上见效、立刻根治

### 替代建议话术
- "非常好" → "口碑很好"
- "最有效" → "很多用户反馈很好"
- "100%安全" → "经过严格检测"
- "立刻见效" → "坚持使用一段时间后"
""",
        ),
        (
            "直播活动策划案例集.md",
            """# 直播活动策划案例集

## 案例1：新店开业直播活动

### 活动主题
"盛大开业，礼惠全城"

### 活动时间
开业当天14:00-22:00

### 活动设计
1. **下单礼**：前100单送开业专属礼包
2. **抽奖礼**：每小时抽免单
3. **阶梯礼**：GMV达1万抽大额红包
4. **分享礼**：邀请好友观看额外抽奖机会

### 活动效果复盘
- 单场GMV：12万
- 新增粉丝：3200人
- 客单价：180元
- 转化率：8.5%

## 案例2：节日主题直播活动

### 活动主题
"618年中狂欢购"

### 预热策略
- 提前7天发布预告短视频
- 社群每日倒计时
- 预约直播享专属优惠

### 活动节奏
- 第一阶段（18-20点）：引流款引爆流量
- 第二阶段（20-22点）：利润款承接转化
- 第三阶段（22-24点）：秒杀款冲GMV

## 案例3：会员专享直播

### 活动特点
- 仅对会员可见的专属直播间
- 价格比日常直播低10%-15%
- 限量新品抢先购
- 专属客服实时服务
""",
        ),
    ],
    "kb_product": [
        (
            "产品知识库总览.md",
            """# 产品知识库总览

## 产品分类体系

### 1. 护肤品类
- 洁面产品
- 护肤水
- 精华液
- 乳液/面霜
- 面膜
- 眼部护理
- 防晒产品

### 2. 美妆品类
- 底妆类
- 彩妆类
- 卸妆类
- 化妆工具

### 3. 身体护理类
- 沐浴产品
- 身体乳
- 手霜
- 磨砂产品

## 产品核心卖点提炼模板

### 卖点描述规范
- 简洁易懂，一句话说清
- 可验证，有数据或证据支撑
- 有差异化，与竞品区隔
- 用户视角，而非产品视角

### 卖点描述案例
- "含有95%天然植物成分" → 事实描述
- "敏感肌测试通过，不刺激" → 安全保障
- "7天可见肤色提亮" → 效果承诺

## 产品禁忌与注意事项

### 成分禁忌
- 孕妇慎用成分清单
- 过敏人群禁忌成分
- 产品搭配禁忌

### 使用场景禁忌
- 日光下禁用
- 与其他产品混用禁忌
- 特定人群禁用提示
""",
        ),
        (
            "本季度主推产品详情.md",
            """# 本季度主推产品详情

## 主推产品1：舒缓保湿面霜

### 产品基本信息
- 产品全称：XX舒缓保湿修护面霜
- 规格：50g
- 售价：298元
- 保质期：3年

### 核心卖点
1. 成分天然：95%天然来源，无香精酒精
2. 修护力强：添加神经酰胺、积雪草精华
3. 温和不刺激：通过敏感肌测试
4. 适用人群广：任何肤质可用，尤其适合敏感肌

### 目标客群
- 主要客群：25-35岁女性
- 肤质特点：干燥、敏感、易泛红
- 需求痛点：需要温和有效的保湿修护

### 产品演示要点
- 质地展示：冰淇淋质地，好推开
- 吸收测试：快速吸收不油腻
- pH测试：弱酸性，亲和皮肤
- 成分讲解：关键成分的作用

## 主推产品2：焕颜精华液

### 产品基本信息
- 产品全称：XX烟酰胺亮肤精华液
- 规格：30ml
- 售价：458元
- 保质期：3年

### 核心卖点
1. 5%烟酰胺：科学浓度，有效提亮
2. 复配传明酸：抑制暗沉源头
3. 质地轻薄：好吸收不粘腻
4. 效果可鉴：28天可见肤色提亮

### 目标客群
- 主要客群：28-40岁女性
- 肤质特点：肤色暗沉、有痘印
- 需求痛点：需要温和有效的提亮产品

## 主推产品3：氨基酸洁面乳

### 产品基本信息
- 产品全称：XX温和氨基酸洁面乳
- 规格：120g
- 售价：128元
- 保质期：3年

### 核心卖点
1. 纯氨基酸表活：温和不刺激
2. 泡沫绵密：像云朵般的洗感
3. 清洁力够：日常淡妆可直接洗净
4. 洗后不紧绷：保留皮肤天然屏障
""",
        ),
    ],
    "kb_compliance": [
        (
            "广告法禁用词详细清单.md",
            """# 广告法禁用词详细清单

## 一、绝对化用语（红色警告）

### 最高级相关
- 最、最佳、最高级、最优、最好
- 顶级、极致、巅峰、完美
- 第一、No.1、Top.1
- 终极、极致、无比

### 绝对化承诺
- 绝对、永久、彻底、完全
- 100%、无效退款、包治百病
- 永不、终身、全方位
- 万能、全能、完美无缺

### 国家级相关
- 国家级、世界级、全球领先
- 国际品质、国际大牌
- 独家、绝无仅有、空前绝后

## 二、虚假承诺（红色警告）

### 效果承诺
- 见效快、立刻有效、马上见效
- 根治、包治百病、永不复发
- 减肥不用节食、美白不用防晒

### 盈利承诺
- 稳赚不赔、一夜暴富
- 保本、零风险、高收益
- 躺赚、睡后收入、轻松赚钱

## 三、虚假宣传（橙色警告）

### 销量排名
- 销量第一、销量冠军、销量领先
- 热销、火爆、爆款
- 除非有真实数据支撑，否则慎用

### 口碑评价
- 全网好评、99%好评
- 用户都说好、大家都在用
- 除非有真实评价数据，否则慎用

## 四、规范替代词建议

### 绝对化替代词
- "最好" → "口碑很好"
- "最有效" → "很多用户反馈不错"
- "第一" → "深受用户喜爱"
- "100%安全" → "经过严格检测"
- "立刻见效" → "坚持使用一段时间后"

### 违禁词检测工具使用指南
1. 文案撰写完成后先自查
2. 使用违禁词检测工具扫描
3. 对检测出的问题进行修改
4. 再次检测确认无误后发布
""",
        ),
        (
            "内部审批流程规范.md",
            """# 内部审批流程规范

## 价格调整审批流程

### 审批权限
- 日常价格调整：主管级审批
- 幅度超过10%：经理级审批
- 超过30%：总监级审批
- 涉及价格体系变更：总裁级审批

### 申请材料
1. 价格调整申请表
2. 调整原因说明
3. 历史价格对比表
4. 预期收益/影响分析
5. 竞品价格对比（如有需要）

## 促销活动审批流程

### 常规活动审批
- 活动计划提前7天提交
- 活动方案需包含：活动主题、时间、规则、预算
- 审批流程：主管 → 经理 → 合规审核

### 大型活动审批
- 活动计划提前30天提交
- 除常规材料外，还需提供：
  - 库存备货计划
  - 人员配置计划
  - 应急处理预案
  - 跨部门协调方案
- 审批流程：主管 → 经理 → 总监 → 合规审核

## 跨部门资源协调审批

### 协调申请流程
1. 发起部门填写资源协调申请单
2. 明确协调事项、所需资源、时间要求
3. 发起部门负责人审批
4. 资源提供部门负责人审批
5. 如资源冲突，提交共同上级协调
6. 审批通过后执行
7. 资源使用情况反馈

## 常见违规案例警示

### 案例1：未经审批调价
**事件**：某门店店长私下给老顾客特殊折扣
**后果**：价格体系混乱，被投诉到物价局
**处理**：通报批评，罚款处理

### 案例2：违规宣传
**事件**：某产品宣传使用违禁词"最有效"
**后果**：被市场监管部门罚款20万
**处理**：相关人员问责，全面整改
""",
        ),
    ],
    "kb_finance": [
        (
            "财务报销管理制度.md",
            """# 财务报销管理制度

## 报销时间规定

### 常规报销
- 月度报销：每月1-10号提交上月报销
- 季度报销：每季度首月15号前提交
- 年度报销：次年1月31日前完成上年度报销

### 紧急报销
- 紧急借款需填写紧急借款申请单
- 事后3个工作日内完成报销冲账
- 未按时报销扣当月绩效

## 报销审批权限

### 常规费用
- 500元以下：部门主管审批
- 500-5000元：部门经理审批
- 5000-20000元：财务经理审批
- 20000元以上：财务总监审批

### 专项费用
- 差旅费用：按差旅制度单独规定
- 业务招待：单次2000元以上需事前审批
- 设备采购：需走采购流程

## 报销凭证要求

### 发票要求
- 发票抬头必须是公司全称
- 发票内容必须与实际业务一致
- 发票日期必须是当年度
- 发票专用章必须清晰

### 其他凭证
- 差旅报销还需提供行程单、登机牌
- 业务招待还需提供招待清单、人员明细
- 采购报销还需提供采购合同、验收单
- 会议报销还需提供会议通知、签到表

## 报销单填写规范

### 填写要点
- 日期准确：填写实际发生日期
- 事由清晰：简明扼要说明事由
- 金额准确：大小写一致
- 附件完整：相关凭证齐全
- 签字齐全：相关责任人签字确认
""",
        ),
        (
            "ROI测算标准方法.md",
            """# ROI测算标准方法

## 计算公式

### 基础公式
ROI = (净增销售额 - 活动成本) / 活动成本 × 100%

### 净增销售额计算
净增销售额 = 活动期总销售额 - 自然增长预期销售额

### 活动成本包含
- 直播费用：场地、设备、人员
- 营销费用：流量采买、优惠券成本
- 商品折扣：日常价与活动价差额
- 赠品成本：赠品的成本价
- 物流成本：活动期间额外物流支出

## 测算口径说明

### 自然增长预期
- 参考历史同期数据
- 考虑季节性因素
- 考虑近期趋势变化

### ROI测算场景

#### 场景1：新品上市直播
假设条件：
- 活动成本：5万
- 自然增长预期：30万
- 活动期目标销售额：80万

计算：
净增销售额 = 80万 - 30万 = 50万
ROI = (50万 - 5万) / 5万 × 100% = 900%

#### 场景2：清仓直播
假设条件：
- 活动成本：2万
- 自然增长预期：5万
- 活动期目标销售额：20万

计算：
净增销售额 = 20万 - 5万 = 15万
ROI = (15万 - 2万) / 2万 × 100% = 650%

## 项目评价标准

### ROI等级划分
- ≥500%：优秀项目，大力推荐
- 300%-500%：良好项目，可以执行
- 150%-300%：一般项目，谨慎评估
- <150%：较差项目，不建议执行

### 其他评价维度
- 品牌曝光度
- 新客获取数
- 复购率提升
- 库存优化效果

## 常见测算误区

### 误区1：不扣除自然增长
错误做法：直接用活动期总销售额计算
正确做法：扣除自然增长，只算活动带来的增量

### 误区2：成本计算不全
错误做法：只算直接投入
正确做法：全链路成本都要算

### 误区3：只看短期ROI
错误做法：只看当次ROI
正确做法：考虑长期影响，如复购、品牌价值
""",
        ),
        (
            "费用归属与成本分摊规则.md",
            """# 费用归属与成本分摊规则

## 费用归属原则

### 归属判断标准
- 谁受益谁承担
- 谁发起谁承担
- 合同明确的按合同执行

### 常见费用归属
- 门店活动 → 对应门店成本中心
- 区域活动 → 对应区域成本中心
- 总部活动 → 按受益门店/区域分摊
- 线上活动 → 独立电商成本中心

## 成本分摊规则

### 按客流占比分摊
适用场景：区域统一活动、各门店共同受益
计算方式：某门店分摊额 = 总成本 × (该门店预计客流 / 总预计客流)

### 按销售占比分摊
适用场景：品类营销活动
计算方式：某品类分摊额 = 总成本 × (该品类预计销售 / 总预计销售)

### 按人头均摊
适用场景：公共培训、系统上线等
计算方式：人均分摊额 = 总成本 / 总人数

## 成本分摊案例

### 案例1：区域直播活动分摊
假设：A区域3个门店做联合直播，总成本5万
预计客流：
- 门店1：300人 (30%)
- 门店2：400人 (40%)
- 门店3：300人 (30%)

分摊结果：
- 门店1：5万 × 30% = 1.5万
- 门店2：5万 × 40% = 2.0万
- 门店3：5万 × 30% = 1.5万

### 案例2：品牌联合活动分摊
假设：品牌A、B、C联合活动，总成本10万
预计销售贡献：
- 品牌A：25万 (25%)
- 品牌B：45万 (45%)
- 品牌C：30万 (30%)

分摊结果：
- 品牌A：10万 × 25% = 2.5万
- 品牌B：10万 × 45% = 4.5万
- 品牌C：10万 × 30% = 3.0万
""",
        ),
    ],
    "kb_hr": [
        (
            "新员工入职指南.md",
            """# 新员工入职指南

## 入职手续办理

### 第一天到岗
1. 前台签到，领取员工手册
2. 人事部门办理入职登记
3. 提交材料：身份证、学历证复印件、一寸照片
4. 签署劳动合同、保密协议
5. 领取工牌、工位钥匙、电脑设备

### 入职培训
1. 公司文化培训（上午）
2. 部门介绍与岗位职责（下午）
3. 系统操作培训（第二天）
4. 业务流程培训（第三天）

### 试用期规定
- 试用期3个月
- 试用期内双方可提前3天解除合同
- 试用期考核通过后转正

## 考勤管理规定

### 工作时间
- 周一至周五：9:00-18:00
- 午休时间：12:00-13:30
- 周末双休，法定节假日休息

### 考勤规则
- 9:00前打卡算迟到
- 18:00前走算早退
- 全勤奖：无迟到早退请假

### 请假流程
- 事假：提前1天申请，年假抵扣或扣薪
- 病假：凭医院证明，发病假工资
- 年假：按工龄计算，提前申请
""",
        ),
        (
            "绩效考核制度.md",
            """# 绩效考核制度

## 考核周期与方式

### 月度考核
- 时间：每月5号前完成上月考核
- 内容：业绩指标、工作完成情况
- 权重：业绩60%，工作表现40%

### 季度考核
- 时间：每季度首月10号前完成
- 内容：季度目标完成、能力成长
- 权重：业绩70%，能力30%

### 年度考核
- 时间：次年1月完成
- 内容：全年综合表现
- 结果应用：晋升、调薪、奖金

## 绩效考核指标示例

### 运营岗
- GMV完成率：权重30%
- 转化率：权重20%
- 新增粉丝数：权重20%
- 复购率：权重15%
- 内容产出：权重15%

### 销售岗
- 销售额：权重40%
- 新客数：权重20%
- 客单价：权重15%
- 老客复购：权重15%
- 客户满意度：权重10%
""",
        ),
    ],
    "kb_supply_chain": [
        (
            "库存管理规范.md",
            """# 库存管理规范

## 库存盘点

### 盘点频率
- 日常盘点：每周一
- 月度盘点：每月最后一个工作日
- 季度盘点：每季度末
- 年度盘点：12月31日

### 盘点流程
1. 停止出入库
2. 系统库存冻结
3. 实物盘点
4. 账实核对
5. 差异分析
6. 盘盈盘亏处理

## 库存预警

### 安全库存设置
- A类商品：30天销量
- B类商品：45天销量
- C类商品：60天销量

### 预警触发
- 库存低于安全库存：预警
- 库存低于7天销量：紧急预警
- 库存超120天销量：滞销预警
""",
        ),
        (
            "供应商管理办法.md",
            """# 供应商管理办法

## 供应商分级

### 供应商等级划分
- A级供应商：核心供应商，占采购额70%
- B级供应商：重要供应商，占采购额20%
- C级供应商：一般供应商，占采购额10%

### 供应商评价指标
- 产品质量：权重35%
- 交货准时率：权重25%
- 价格竞争力：权重20%
- 服务响应：权重20%

## 供应商合作流程

1. 供应商开发与选择
2. 样品测试与验证
3. 商务谈判
4. 合同签署
5. 小批量试单
6. 大批量合作
7. 持续评价与改进
""",
        ),
    ],
}

# ==========================================
# Prompt模板（大幅扩充）
# ==========================================
PROMPTS = [
    {
        "prompt_key": "prompt_live_script_v1",
        "name": "直播脚本生成Prompt",
        "template": """你是资深门店直播运营专家。请根据以下信息生成一份完整的直播脚本：

【产品信息】
{{product_info}}

【目标客群】
{{customer_profile}}

【直播时长】
{{duration_minutes}}分钟

【要求】
1. 脚本需包含以下环节：开场预热、产品讲解、互动转化、收官总结
2. 每个环节要有明确的时间节点
3. 突出产品卖点，但要符合广告合规要求
4. 包含互动引导话术
5. 要有逼单话术但不要过度营销
6. 提供3-5个备选开头和结尾

请输出完整的直播脚本。""",
        "variables": [
            {"name": "product_info", "type": "object", "required": True},
            {"name": "customer_profile", "type": "object", "required": True},
            {"name": "duration_minutes", "type": "integer", "required": False},
        ],
        "owner": "运营部",
    },
    {
        "prompt_key": "prompt_roi_estimate_v1",
        "name": "活动ROI测算Prompt",
        "template": """你是经验丰富的财务分析专家。请测算以下活动的ROI并给出建议：

【活动预算】
预算金额：{{budget}}元
成本明细：{{cost_details}}

【预期收益】
预计销售额：{{expected_revenue}}元
自然增长预期：{{natural_growth}}元

【请分析】
1. 计算ROI，给出具体数值
2. 分析这个项目的投资价值
3. 给出是否建议执行的明确结论
4. 如执行，给出风险提示和优化建议
5. 给出关键监控指标建议

请用结构化方式输出分析结果。""",
        "variables": [
            {"name": "budget", "type": "number", "required": True},
            {"name": "expected_revenue", "type": "number", "required": True},
            {"name": "cost_details", "type": "string", "required": False},
            {"name": "natural_growth", "type": "number", "required": False},
        ],
        "owner": "财务部",
    },
    {
        "prompt_key": "prompt_product_desc_v1",
        "name": "产品卖点提炼Prompt",
        "template": """你是专业的产品策划专家。请为以下产品提炼卖点：

【产品基本信息】
产品名称：{{product_name}}
类别：{{category}}
价格：{{price}}元
主要成分/功能：{{features}}

【目标客群】
{{target_audience}}

【请完成】
1. 提炼3-5个核心卖点
2. 每个卖点用FABE法则组织（特征、优势、利益、证据）
3. 撰写适合直播的产品讲解话术
4. 撰写适合朋友圈的推广文案
5. 指出宣传中需要注意的合规事项

请输出完整的产品营销话术方案。""",
        "variables": [
            {"name": "product_name", "type": "string", "required": True},
            {"name": "category", "type": "string", "required": True},
            {"name": "price", "type": "number", "required": True},
            {"name": "features", "type": "string", "required": True},
            {"name": "target_audience", "type": "string", "required": True},
        ],
        "owner": "商品部",
    },
    {
        "prompt_key": "prompt_training_plan_v1",
        "name": "培训课程设计Prompt",
        "template": """你是企业培训专家。请根据以下需求设计培训课程：

【培训主题】
{{training_topic}}

【培训对象】
{{audience}}

【培训时长】
{{duration_hours}}小时

【培训目标】
{{training_goals}}

【请设计】
1. 培训课程大纲，分模块设计
2. 每个模块的内容要点
3. 授课方式建议（讲解/演示/案例/互动）
4. 课程教具和材料清单
5. 培训效果评估方法
6. 课后作业与实践任务

请输出完整的培训课程设计方案。""",
        "variables": [
            {"name": "training_topic", "type": "string", "required": True},
            {"name": "audience", "type": "string", "required": True},
            {"name": "duration_hours", "type": "number", "required": True},
            {"name": "training_goals", "type": "string", "required": True},
        ],
        "owner": "商学院",
    },
    {
        "prompt_key": "prompt_performance_analysis_v1",
        "name": "绩效分析Prompt",
        "template": """你是人事分析专家。请分析以下员工绩效数据：

【员工信息】
姓名：{{employee_name}}
岗位：{{position}}
入职时间：{{join_date}}

【本期绩效数据】
{{performance_data}}

【历史数据对比】
{{history_data}}

【请完成】
1. 本期绩效评价
2. 优点与不足分析
3. 与历史数据对比的变化趋势
4. 能力提升建议
5. 下期目标设定建议
6. 培训与发展建议

请输出结构化的绩效分析报告。""",
        "variables": [
            {"name": "employee_name", "type": "string", "required": True},
            {"name": "position", "type": "string", "required": True},
            {"name": "performance_data", "type": "object", "required": True},
            {"name": "history_data", "type": "object", "required": False},
        ],
        "owner": "人事部",
    },
    {
        "prompt_key": "prompt_inventory_forecast_v1",
        "name": "库存预测Prompt",
        "template": """你是供应链管理专家。请分析以下销售数据并给出库存建议：

【商品信息】
商品名称：{{product_name}}
商品编号：{{product_id}}
当前库存：{{current_inventory}}

【历史销售数据】
{{sales_history}}

【促销活动计划】
{{promotion_plan}}

【请分析】
1. 历史销售趋势分析
2. 未来30天销量预测
3. 安全库存建议
4. 是否需要补货及补货数量
5. 库存风险预警（如有）
6. 促销备货建议

请输出完整的库存分析建议报告。""",
        "variables": [
            {"name": "product_name", "type": "string", "required": True},
            {"name": "product_id", "type": "string", "required": True},
            {"name": "current_inventory", "type": "number", "required": True},
            {"name": "sales_history", "type": "object", "required": True},
            {"name": "promotion_plan", "type": "string", "required": False},
        ],
        "owner": "供应链部",
    },
]

# ==========================================
# Skill定义（大幅扩充）
# ==========================================
SKILLS = [
    {
        "skill_key": "skill_live_script",
        "name": "直播话术生成Skill",
        "description": "根据产品卖点、目标客群、直播时长生成合规直播脚本",
        "type": "workflow_skill",
        "business_domain": "operation",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_info": {"type": "object"},
                "customer_profile": {"type": "object"},
                "duration_minutes": {"type": "integer"},
            },
            "required": ["product_info", "customer_profile"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "opening": {"type": "string"},
                "product_introduction": {"type": "array"},
                "conversion_script": {"type": "string"},
                "closing": {"type": "string"},
                "risk_warnings": {"type": "array"},
            },
        },
        "dependencies": ["kb_product", "kb_compliance", "tool_forbidden_word_check"],
        "allowed_agent_roles": ["operation_agent", "business_school_agent", "master_agent"],
        "prompt_key": "prompt_live_script_v1",
    },
    {
        "skill_key": "skill_roi_estimate",
        "name": "ROI测算Skill",
        "description": "根据活动预算与预计收益测算ROI",
        "type": "prompt_skill",
        "business_domain": "finance",
        "input_schema": {
            "type": "object",
            "properties": {
                "budget": {"type": "number"},
                "expected_revenue": {"type": "number"},
                "cost_details": {"type": "string"},
                "natural_growth": {"type": "number"},
            },
            "required": ["budget", "expected_revenue"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "roi": {"type": "number"},
                "analysis": {"type": "string"},
                "recommendation": {"type": "string"},
                "metrics": {"type": "array"},
            },
        },
        "dependencies": ["kb_finance"],
        "allowed_agent_roles": ["finance_agent", "product_submission_agent", "operation_agent", "master_agent"],
        "prompt_key": "prompt_roi_estimate_v1",
    },
    {
        "skill_key": "skill_product_description",
        "name": "产品卖点提炼Skill",
        "description": "为产品提炼专业卖点并生成营销话术",
        "type": "prompt_skill",
        "business_domain": "product",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_name": {"type": "string"},
                "category": {"type": "string"},
                "price": {"type": "number"},
                "features": {"type": "string"},
                "target_audience": {"type": "string"},
            },
            "required": ["product_name", "category", "price", "features", "target_audience"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "selling_points": {"type": "array"},
                "live_script": {"type": "string"},
                "social_media_copy": {"type": "string"},
                "compliance_notes": {"type": "array"},
            },
        },
        "dependencies": ["kb_product", "kb_compliance", "tool_forbidden_word_check"],
        "allowed_agent_roles": ["product_submission_agent", "operation_agent", "master_agent"],
        "prompt_key": "prompt_product_desc_v1",
    },
    {
        "skill_key": "skill_training_plan",
        "name": "培训课程设计Skill",
        "description": "根据培训需求设计完整的培训课程方案",
        "type": "prompt_skill",
        "business_domain": "business_school",
        "input_schema": {
            "type": "object",
            "properties": {
                "training_topic": {"type": "string"},
                "audience": {"type": "string"},
                "duration_hours": {"type": "number"},
                "training_goals": {"type": "string"},
            },
            "required": ["training_topic", "audience", "duration_hours", "training_goals"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "course_outline": {"type": "array"},
                "teaching_methods": {"type": "array"},
                "materials": {"type": "array"},
                "assessment_method": {"type": "string"},
            },
        },
        "dependencies": ["kb_store_operation"],
        "allowed_agent_roles": ["business_school_agent", "hr_agent", "master_agent"],
        "prompt_key": "prompt_training_plan_v1",
    },
    {
        "skill_key": "skill_performance_analysis",
        "name": "绩效分析Skill",
        "description": "分析员工绩效数据并给出发展建议",
        "type": "prompt_skill",
        "business_domain": "hr",
        "input_schema": {
            "type": "object",
            "properties": {
                "employee_name": {"type": "string"},
                "position": {"type": "string"},
                "performance_data": {"type": "object"},
                "history_data": {"type": "object"},
            },
            "required": ["employee_name", "position", "performance_data"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "evaluation": {"type": "string"},
                "strengths": {"type": "array"},
                "areas_for_improvement": {"type": "array"},
                "development_suggestions": {"type": "array"},
                "next_period_goals": {"type": "array"},
            },
        },
        "dependencies": ["kb_hr"],
        "allowed_agent_roles": ["hr_agent", "master_agent"],
        "prompt_key": "prompt_performance_analysis_v1",
    },
    {
        "skill_key": "skill_inventory_forecast",
        "name": "库存预测Skill",
        "description": "分析销售数据并给出库存建议",
        "type": "prompt_skill",
        "business_domain": "supply_chain",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_name": {"type": "string"},
                "product_id": {"type": "string"},
                "current_inventory": {"type": "number"},
                "sales_history": {"type": "object"},
                "promotion_plan": {"type": "string"},
            },
            "required": ["product_name", "product_id", "current_inventory", "sales_history"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "sales_trend": {"type": "string"},
                "forecast": {"type": "number"},
                "safety_stock_recommendation": {"type": "number"},
                "restocking_needed": {"type": "boolean"},
                "recommended_restock_amount": {"type": "number"},
                "risk_warnings": {"type": "array"},
            },
        },
        "dependencies": ["kb_supply_chain"],
        "allowed_agent_roles": ["supply_chain_agent", "product_submission_agent", "master_agent"],
        "prompt_key": "prompt_inventory_forecast_v1",
    },
    {
        "skill_key": "skill_merchant_evaluation",
        "name": "加盟商评估Skill",
        "description": "评估加盟商资质并给出合作建议",
        "type": "workflow_skill",
        "business_domain": "merchant",
        "input_schema": {
            "type": "object",
            "properties": {
                "merchant_info": {"type": "object"},
                "site_info": {"type": "object"},
                "financial_info": {"type": "object"},
            },
            "required": ["merchant_info", "site_info"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "score": {"type": "number"},
                "level": {"type": "string"},
                "strengths": {"type": "array"},
                "risks": {"type": "array"},
                "recommendation": {"type": "string"},
                "cooperation_plan": {"type": "string"},
            },
        },
        "dependencies": [],
        "allowed_agent_roles": ["merchant_agent", "master_agent"],
        "prompt_key": None,
    },
    {
        "skill_key": "skill_activity_summary",
        "name": "活动总结Skill",
        "description": "分析活动数据并生成完整的总结报告",
        "type": "workflow_skill",
        "business_domain": "operation",
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_name": {"type": "string"},
                "activity_period": {"type": "string"},
                "data_summary": {"type": "object"},
            },
            "required": ["activity_name", "activity_period", "data_summary"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "key_metrics": {"type": "object"},
                "highlights": {"type": "array"},
                "issues": {"type": "array"},
                "improvements": {"type": "array"},
                "next_steps": {"type": "array"},
            },
        },
        "dependencies": ["kb_store_operation"],
        "allowed_agent_roles": ["operation_agent", "business_school_agent", "master_agent"],
        "prompt_key": None,
    },
]

# ==========================================
# Tool定义（从工具注册表自动获取）
# ==========================================
def get_tool_capabilities():
    """从工具注册表获取所有工具的 capability 定义。"""
    capabilities = []

    # 尝试从工具注册表获取定义
    try:
        tool_definitions = ToolRegistry.get_all_definitions()
        for tool_def in tool_definitions:
            capabilities.append({
                "capability_key": tool_def.capability_key,
                "type": "tool",
                "name": tool_def.name,
                "description": tool_def.description,
                "business_domain": tool_def.business_domain,
                "tags": tool_def.tags,
                "scenarios": tool_def.scenarios,
                "input_schema": tool_def.input_schema,
                "output_schema": tool_def.output_schema,
                "security_level": tool_def.security_level,
                "owner_department": tool_def.owner_department,
                "allowed_agent_roles": [],
                "side_effect": tool_def.side_effect,
                "ref_id": tool_def.capability_key,
                "metadata": tool_def.metadata,
                "timeout_ms": tool_def.timeout_ms,
                "examples": tool_def.examples,
            })
    except Exception:
        pass

    # 添加其他示例工具定义
    additional_tools = [
        {
            "capability_key": "tool_customer_segment",
            "type": "tool",
            "name": "客户分层分析工具",
            "description": "根据客户数据进行分层分析，给出运营建议",
            "business_domain": "operation",
            "tags": ["客户分析", "分层", "运营"],
            "scenarios": ["客户运营", "活动策划", "营销策略制定"],
            "input_schema": {
                "type": "object",
                "properties": {
                    "customer_data": {"type": "array"},
                    "segment_rules": {"type": "object"},
                },
                "required": ["customer_data"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "segments": {"type": "array"},
                    "segment_distribution": {"type": "object"},
                    "recommendations": {"type": "array"},
                },
            },
            "security_level": "internal",
            "owner_department": "运营部",
            "allowed_agent_roles": ["operation_agent", "product_submission_agent", "master_agent"],
            "side_effect": "read_only",
            "ref_id": "tool_customer_segment",
        },
        {
            "capability_key": "tool_price_optimization",
            "type": "tool",
            "name": "价格优化建议工具",
            "description": "根据历史数据和竞品信息给出定价建议",
            "business_domain": "finance",
            "tags": ["定价", "价格策略", "竞品分析"],
            "scenarios": ["新品定价", "促销定价", "价格调整评估"],
            "input_schema": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "cost_data": {"type": "object"},
                    "competitor_prices": {"type": "array"},
                },
                "required": ["product_id", "cost_data"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "recommended_price_range": {"type": "object"},
                    "price_sensitivity": {"type": "string"},
                    "expected_volume": {"type": "number"},
                    "margin_analysis": {"type": "object"},
                },
            },
            "security_level": "confidential",
            "owner_department": "财务部",
            "allowed_agent_roles": ["finance_agent", "product_submission_agent", "master_agent"],
            "side_effect": "read_only",
            "ref_id": "tool_price_optimization",
        },
    ]

    # 合并，避免重复
    existing_keys = {c["capability_key"] for c in capabilities}
    for tool in additional_tools:
        if tool["capability_key"] not in existing_keys:
            capabilities.append(tool)

    return capabilities


CAPABILITIES_EXTRA = get_tool_capabilities()

# ==========================================
# 知识库元数据
# ==========================================
KB_DOMAIN_MAP = {
    "kb_store_operation": ("门店运营知识库", "operation", "internal"),
    "kb_product": ("产品知识库", "product", "internal"),
    "kb_compliance": ("合规规则库", "compliance", "internal"),
    "kb_finance": ("财务报销与预算规则库", "finance", "confidential"),
    "kb_hr": ("人事管理知识库", "hr", "internal"),
    "kb_supply_chain": ("供应链管理知识库", "supply_chain", "internal"),
}


# ==========================================
# 帮助函数
# ==========================================
async def get_or_create_agent(db, agent_key, name, role, domain, dept, description=None, is_master=False) -> tuple[Agent, bool]:
    result = await db.execute(select(Agent).where(Agent.agent_key == agent_key))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    agent = Agent(
        agent_key=agent_key,
        name=name,
        role=role,
        business_domain=domain,
        owner_department=dept,
        description=description,
        status="active",
        api_key=generate_api_key("agent"),
        is_master=is_master,
        supported_tasks=[],
    )
    db.add(agent)
    await db.flush()
    return agent, True


async def get_or_create_kb(db, kb_key, name, domain, security_level="internal") -> tuple[KnowledgeBase, bool]:
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.kb_key == kb_key))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    kb = KnowledgeBase(
        kb_key=kb_key,
        name=name,
        business_domain=domain,
        owner_department=domain,
        security_level=security_level,
        status="draft",
        retrieval_config={}
    )
    db.add(kb)
    await db.flush()
    return kb, True


async def get_or_create_capability(db, **kwargs) -> tuple[Capability, bool]:
    result = await db.execute(select(Capability).where(Capability.capability_key == kwargs["capability_key"]))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    metadata = kwargs.pop("metadata", {})
    cap = Capability(**kwargs, metadata_=metadata, status="published")
    db.add(cap)
    await db.flush()
    return cap, True


async def get_or_create_policy(db, policy_key, **kwargs) -> tuple[Policy, bool]:
    result = await db.execute(select(Policy).where(Policy.policy_key == policy_key))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    policy = Policy(policy_key=policy_key, status="active", **kwargs)
    db.add(policy)
    await db.flush()
    return policy, True


async def get_or_create_capability_permission(
    db,
    capability: Capability,
    subject_type: str,
    subject_code: str,
    permission: str,
    conditions: dict | None = None,
    status: str = "active",
) -> tuple[CapabilityPermission, bool]:
    result = await db.execute(
        select(CapabilityPermission).where(
            CapabilityPermission.capability_id == capability.id,
            CapabilityPermission.subject_type == subject_type,
            CapabilityPermission.subject_code == subject_code,
            CapabilityPermission.permission == permission,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    perm = CapabilityPermission(
        capability_id=capability.id,
        subject_type=subject_type,
        subject_code=subject_code,
        permission=permission,
        conditions=conditions or {},
        status=status,
    )
    db.add(perm)
    await db.flush()
    return perm, True


# ==========================================
# 主种子函数
# ==========================================
async def seed() -> None:
    await create_all_tables()
    llm = get_llm_provider()
    created_keys: list[tuple[str, str, str]] = []
    all_credentials: dict[str, str] = {}

    async with AsyncSessionLocal() as db:
        # --- Admin user ---
        result = await db.execute(select(AdminUser).where(AdminUser.username == "admin"))
        admin = result.scalar_one_or_none()
        if admin is None:
            admin = AdminUser(
                username="admin",
                display_name="平台管理员",
                role="platform_admin",
                api_key=generate_api_key("admin"),
                status="active",
            )
            db.add(admin)
            await db.flush()
            created_keys.append(("admin_user", "admin", admin.api_key))
        all_credentials["admin"] = admin.api_key

        # --- Agents ---
        agent_map: dict[str, Agent] = {}
        for agent_key, name, role, domain, dept, description in BUSINESS_AGENTS:
            agent, is_new = await get_or_create_agent(db, agent_key, name, role, domain, dept, description)
            agent_map[role] = agent
            if is_new:
                created_keys.append(("agent", agent_key, agent.api_key))
            all_credentials[agent_key] = agent.api_key

        master, is_new = await get_or_create_agent(
            db, "master_agent_001", "主控Agent", "master_agent", None, "多Agent协作系统",
            description="负责协调各业务Agent完成复杂任务的主控Agent",
            is_master=True
        )
        agent_map["master_agent"] = master
        if is_new:
            created_keys.append(("agent", "master_agent_001", master.api_key))
        all_credentials["master_agent_001"] = master.api_key

        await db.flush()

        # --- Knowledge bases + documents ---
        kb_service = KnowledgeService(db, llm)
        kb_map: dict[str, KnowledgeBase] = {}
        for kb_key, (name, domain, level) in KB_DOMAIN_MAP.items():
            kb, is_new = await get_or_create_kb(db, kb_key, name, domain, level)
            kb_map[kb_key] = kb

            if is_new and kb_key in DOCS:
                # 为每个知识库上传多个文档
                for filename, content in DOCS[kb_key]:
                    doc = await kb_service.upload_document(kb, filename, content.encode("utf-8"), security_level=level)
                    await kb_service.publish_document(doc)
                kb.status = "published"
                await db.flush()

        # --- Prompts ---
        for p in PROMPTS:
            result = await db.execute(select(PromptTemplate).where(PromptTemplate.prompt_key == p["prompt_key"]))
            if result.scalar_one_or_none() is None:
                prompt = PromptTemplate(
                    prompt_key=p["prompt_key"],
                    name=p["name"],
                    template=p["template"],
                    variables=p["variables"],
                    owner=p["owner"],
                    status="published",
                )
                db.add(prompt)
        await db.flush()

        # --- Skills ---
        for s in SKILLS:
            result = await db.execute(select(Skill).where(Skill.skill_key == s["skill_key"]))
            if result.scalar_one_or_none() is None:
                skill = Skill(**s, status="published")
                db.add(skill)
        await db.flush()

        # --- Capabilities: wrap KB / Skill / Prompt / Agent / Tool as searchable capabilities ---
        for kb_key, (name, domain, level) in KB_DOMAIN_MAP.items():
            kb = kb_map.get(kb_key)
            if kb:
                await get_or_create_capability(
                    db,
                    capability_key=kb_key,
                    type="knowledge_base",
                    name=name,
                    description=f"{name}，业务域={domain}，包含业务相关的知识文档、规范流程",
                    business_domain=domain,
                    tags=[domain, "知识库"],
                    scenarios=[
                        f"当需要{domain}相关的知识时搜索此知识库",
                        f"当需要查询{domain}相关的规则流程时使用",
                    ],
                    input_schema={"query": "string", "top_k": "integer"},
                    output_schema={"chunks": "array", "citations": "array"},
                    security_level=level,
                    owner_department=domain,
                    allowed_agent_roles=[],
                    ref_id=kb_key,
                )

        for s in SKILLS:
            await get_or_create_capability(
                db,
                capability_key=s["skill_key"],
                type="skill",
                name=s["name"],
                description=s["description"],
                business_domain=s["business_domain"],
                tags=[s["business_domain"], "skill", "能力"],
                scenarios=[],
                input_schema=s["input_schema"],
                output_schema=s["output_schema"],
                security_level="internal",
                owner_department=s["business_domain"],
                allowed_agent_roles=s["allowed_agent_roles"],
                ref_id=s["skill_key"],
            )

        for p in PROMPTS:
            await get_or_create_capability(
                db,
                capability_key=p["prompt_key"],
                type="prompt",
                name=p["name"],
                description=f"Prompt模板：{p['name']}",
                business_domain=p["owner"],
                tags=[p["owner"], "prompt", "模板"],
                scenarios=[],
                input_schema={
                    "type": "object",
                    "properties": {var["name"]: var.get("type", "string") for var in p["variables"]},
                    "required": [var["name"] for var in p["variables"] if var.get("required")],
                },
                output_schema={"rendered": "string"},
                security_level="internal",
                owner_department=p["owner"],
                allowed_agent_roles=[],
                ref_id=p["prompt_key"],
            )

        for cap_kwargs in CAPABILITIES_EXTRA:
            await get_or_create_capability(db, **cap_kwargs)

        # --- Capability permissions ---
        async def cap_by_key(capability_key: str) -> Capability:
            result = await db.execute(select(Capability).where(Capability.capability_key == capability_key))
            capability = result.scalar_one()
            return capability

        explicit_permissions = [
            ("kb_store_operation", "role", "operation_agent", ["discover", "invoke"]),
            ("kb_product", "role", "product_submission_agent", ["discover", "invoke"]),
            ("kb_compliance", "role", "operation_agent", ["discover", "invoke"]),
            ("kb_compliance", "role", "product_submission_agent", ["discover", "invoke"]),
            ("kb_compliance", "role", "finance_agent", ["discover", "invoke"]),
            ("kb_finance", "role", "finance_agent", ["discover", "invoke"]),
            ("kb_hr", "role", "hr_agent", ["discover", "invoke"]),
            ("kb_supply_chain", "role", "supply_chain_agent", ["discover", "invoke"]),
            ("skill_live_script", "role", "operation_agent", ["discover", "invoke"]),
            ("skill_live_script", "role", "business_school_agent", ["discover", "invoke"]),
            ("skill_live_script", "role", "master_agent", ["discover", "invoke"]),
            ("skill_roi_estimate", "role", "finance_agent", ["discover", "invoke"]),
            ("skill_roi_estimate", "role", "operation_agent", ["discover", "invoke"]),
            ("skill_roi_estimate", "role", "product_submission_agent", ["discover", "invoke"]),
            ("skill_product_description", "role", "product_submission_agent", ["discover", "invoke"]),
            ("skill_product_description", "role", "operation_agent", ["discover", "invoke"]),
            ("skill_training_plan", "role", "business_school_agent", ["discover", "invoke"]),
            ("skill_training_plan", "role", "hr_agent", ["discover", "invoke"]),
            ("skill_performance_analysis", "role", "hr_agent", ["discover", "invoke"]),
            ("skill_inventory_forecast", "role", "supply_chain_agent", ["discover", "invoke"]),
            ("skill_merchant_evaluation", "role", "merchant_agent", ["discover", "invoke"]),
            ("skill_activity_summary", "role", "operation_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "operation_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "finance_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "product_submission_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "merchant_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "supply_chain_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "hr_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "business_school_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "master_agent", ["discover", "invoke"]),
            ("tool_customer_segment", "role", "operation_agent", ["discover", "invoke"]),
            ("tool_price_optimization", "role", "finance_agent", ["discover", "invoke"]),
            ("tool_price_optimization", "role", "product_submission_agent", ["discover", "invoke"]),
        ]
        for capability_key, subject_type, subject_code, permissions in explicit_permissions:
            try:
                capability = await cap_by_key(capability_key)
                for permission in permissions:
                    await get_or_create_capability_permission(db, capability, subject_type, subject_code, permission)
            except Exception:
                pass

        # --- Agents as Capabilities ---
        for agent_key, name, role, domain, dept, description in BUSINESS_AGENTS:
            await get_or_create_capability(
                db,
                capability_key=f"agent_{role}",
                type="agent",
                name=name,
                description=f"{name}，业务域={domain}，可处理该领域相关子任务",
                business_domain=domain,
                tags=[domain, "agent"],
                scenarios=[],
                input_schema={"task": "string", "context": "object"},
                output_schema={"result": "object"},
                security_level="internal",
                owner_department=dept,
                allowed_agent_roles=["master_agent"],
                ref_id=agent_key,
            )

        # --- Policies ---
        domain_policies = [
            ("policy_hr_own_domain", ["hr_agent"], ["hr"]),
            ("policy_finance_own_domain", ["finance_agent"], ["finance"]),
            ("policy_product_own_domain", ["product_submission_agent"], ["product"]),
            ("policy_supply_chain_own_domain", ["supply_chain_agent"], ["supply_chain"]),
            ("policy_merchant_own_domain", ["merchant_agent"], ["merchant"]),
            ("policy_operation_own_domain", ["operation_agent"], ["operation"]),
            ("policy_business_school_own_domain", ["business_school_agent"], ["operation", "business_school"]),
        ]
        for policy_key, roles, domains in domain_policies:
            await get_or_create_policy(
                db,
                policy_key,
                name=policy_key,
                effect="allow",
                subject={"agent_role": roles},
                resource={"business_domain": domains},
                actions=["search", "invoke"],
                conditions={},
            )

        await get_or_create_policy(
            db,
            "policy_compliance_shared",
            name="合规能力共享",
            effect="allow",
            subject={"agent_role": [role for _, _, role, _, _, _ in BUSINESS_AGENTS]},
            resource={"business_domain": ["compliance"]},
            actions=["search", "invoke"],
            conditions={},
        )

        await get_or_create_policy(
            db,
            "policy_roi_skill_cross_domain",
            name="ROI测算Skill跨域复用",
            effect="allow",
            subject={"agent_role": ["operation_agent", "product_submission_agent"]},
            resource={"business_domain": ["finance"], "security_level": ["internal"]},
            actions=["search", "invoke"],
            conditions={},
        )

        await db.commit()

    creds_dir = Path(".local")
    creds_dir.mkdir(exist_ok=True)
    creds_path = creds_dir / "seed_credentials.json"
    creds_path.write_text(json.dumps(all_credentials, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 80)
    print("完整种子数据灌入完成。")
    if created_keys:
        print("\n新创建的身份 API Key：")
        for kind, key, api_key in created_keys:
            print(f"  [{kind}] {key} -> {api_key}")
    else:
        print("\n所有种子数据均已存在，未创建新身份。")
    print(f"\n全部身份的 API Key 已写入 {creds_path.resolve()}")
    print("\n已创建的数据概览：")
    print(f"  - Agents: {len(BUSINESS_AGENTS) + 1} 个")
    print(f"  - 知识库: {len(KB_DOMAIN_MAP)} 个，含多篇文档")
    print(f"  - Skills: {len(SKILLS)} 个")
    print(f"  - Prompts: {len(PROMPTS)} 个")
    print(f"  - Tools: {len(CAPABILITIES_EXTRA)} 个")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(seed())
