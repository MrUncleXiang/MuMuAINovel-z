import { useEffect, useMemo, useState } from 'react';
import { Select, Tag, theme } from 'antd';

interface SkillSummary {
  template_key: string;
  template_name: string;
  description: string;
  category: string;
}

interface Props {
  value?: string;
  onChange?: (value?: string) => void;
  disabled?: boolean;
  /** 场景分类白名单：只显示这些分类的 SKILL；不传则显示全部 */
  categories?: readonly string[];
}

/** 场景 → SKILL 分类映射（避免正文场景出现大纲 SKILL 等错配） */
export const SKILL_CATEGORIES = {
  /** 大纲规划/编辑场景：大纲方法论 + 前置设定 */
  OUTLINE: ['Skill·大纲规划', 'Skill·人设设定'],
  /** 正文创作场景：正文写作 + 润色 */
  WRITING: ['Skill·正文写作', 'Skill·润色'],
  /** 审稿/点评场景：诊断类 + 大纲连贯性 */
  REVIEW: ['Skill·审稿诊断', 'Skill·大纲规划'],
} as const;

/** 生成/编辑弹窗共用的「应用 Skill」选择控件（纯控件，由调用方用 Form.Item 包裹）。 */
export default function SkillSelector({ value, onChange, disabled, categories }: Props) {
  const { token } = theme.useToken();
  const [skills, setSkills] = useState<SkillSummary[]>([]);

  useEffect(() => {
    fetch('/api/skills/list')
      .then(r => (r.ok ? r.json() : []))
      .then((data: unknown) => {
        if (Array.isArray(data)) setSkills(data as SkillSummary[]);
      })
      .catch(() => setSkills([]));
  }, []);

  // 按场景过滤（分类白名单），outline 置顶（仅在其分类内），其余按分类 + 名称排序
  const sortedSkills = useMemo(() => {
    const list = categories && categories.length > 0
      ? skills.filter(s => categories.includes(s.category))
      : [...skills];
    list.sort((a, b) => {
      const pa = a.template_key === 'SKILL_OUTLINE' ? 0 : 1;
      const pb = b.template_key === 'SKILL_OUTLINE' ? 0 : 1;
      if (pa !== pb) return pa - pb;
      return a.category.localeCompare(b.category, 'zh') || a.template_name.localeCompare(b.template_name, 'zh');
    });
    return list;
  }, [skills, categories]);

  const selected = skills.find(s => s.template_key === value);

  return (
    <>
      <Select
        placeholder="不使用 Skill（标准创作）"
        value={value}
        onChange={onChange}
        allowClear
        disabled={disabled}
        showSearch
        optionFilterProp="label"
        style={{ width: '100%' }}
      >
        {sortedSkills.map(skill => (
          <Select.Option key={skill.template_key} value={skill.template_key} label={skill.template_name}>
            <span>{skill.template_name}</span>
            {skill.template_key === 'SKILL_OUTLINE' && (
              <Tag color="blue" style={{ marginLeft: 8 }}>推荐</Tag>
            )}
            <Tag style={{ marginLeft: 8 }}>{skill.category}</Tag>
          </Select.Option>
        ))}
      </Select>
      {selected && (
        <div style={{ color: token.colorSuccess, fontSize: 12, marginTop: 4 }}>
          ✓ {selected.description}
        </div>
      )}
    </>
  );
}
