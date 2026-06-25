interface PageHeaderProps {
  title: string
  description: string
}

export function PageHeader({ title, description }: PageHeaderProps) {
  return (
    <div className="mb-5 sm:mb-8">
      <h2 className="text-xl font-bold tracking-tight text-white sm:text-2xl lg:text-3xl">{title}</h2>
      <p className="mt-1 max-w-2xl text-xs leading-relaxed text-slate-400 sm:mt-1.5 sm:text-sm lg:text-base">
        {description}
      </p>
    </div>
  )
}
